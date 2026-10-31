"""JobRunner: starts one worker subprocess per job and supervises it (design 07 section 4).

It lives in the serve process and is the single DB writer for job rows: workers write only
files and their NDJSON log. A worker survives a serve kill (own session); the next start
adopts it or, if it died, marks the job `interrupted` and re-enqueues the same plan (the stage
graph is idempotent, so resuming means re-planning)."""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from manuallabor.contracts.io import canonical_json
from manuallabor.jobs.providers import ProviderMode
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import JobInfo, RunPlanIn
from manuallabor.state.store import Store, parse_ts

__all__ = ["JobRunner", "job_info"]

ADOPT_MAX_SILENCE = 30.0
KILL_AFTER = 5.0
TICK = 0.5
TERMINAL = {"done", "failed", "cancelled", "interrupted"}
# Only pipeline runs fold into an identical queued job (design 07 section 18): a run re-plans from
# the current state when it starts, so a second identical run behind it would find nothing to
# do. Exports, agent passes and ingests have per-job side effects and never fold.
COLLAPSIBLE = {"run"}
# what a merged row shows of its survivor while that one is queued or running (not stored)
_MIRRORED = (
    "progress", "units_done", "units_total", "node", "doc", "message",
    "step_done", "step_total", "step_unit",
)  # fmt: skip
# what a merged row takes from its survivor when that one ends (stored, same transaction)
_SETTLED = (
    "status", "finished_at", "error", "progress", "units_done", "units_total", "node", "doc",
    "message",
)  # fmt: skip
# Finished job rows are pruned (at start and hourly) once they are older than PRUNE_AFTER, beyond
# the newest PRUNE_KEEP of them. A finished row is read for three things: the idempotency of a
# replayed request (`enqueue(request_id=)`: a client retry, seconds to minutes later), the Jobs
# bar and `/api/jobs` (recent work), and its log (`/api/jobs/{id}/log`, kept on disk). A week
# covers every retry and a week-end away; the newest PRUNE_KEEP stay so a project reopened after
# a long break still shows what last ran. Queued and running rows are never pruned.
PRUNE_AFTER = timedelta(days=7)
PRUNE_KEEP = 200
PRUNE_EVERY = 3600.0  # seconds between prunes while serving
# The worker runs below the serve process's priority: model and parse work is CPU-bound and
# background by design, the API must stay interactive while it runs (on a 2-core machine a
# Docling parse at equal priority delayed every request; design 07 section 16.4).
WORKER_NICE = 10


def job_info(row: Any) -> JobInfo:
    return JobInfo(
        id=f"job-{row['n']:06d}",
        kind=row["kind"],
        plan=json.loads(row["plan"]),
        status=row["status"],
        progress=min(1.0, float(row["progress"])),
        units_done=row["units_done"],
        units_total=row["units_total"],
        node=row["node"],
        doc=row["doc"],
        message=row["message"],
        created_at=parse_ts(row["created_at"]),
        started_at=None if row["started_at"] is None else parse_ts(row["started_at"]),
        finished_at=None if row["finished_at"] is None else parse_ts(row["finished_at"]),
        pid=row["pid"],
        error=row["error"],
        resumed_from=row["resumed_from"],
        merged_into=row["merged_into"],
    )


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _summary(o: dict[str, Any]) -> str | None:
    if "stage" not in o:
        return None
    parts = [str(o.get("stage")), str(o.get("doc", ""))]
    head = " ".join(p for p in parts if p)
    extra = [f"{k} {o[k]}" for k in ("status", "llm_calls") if o.get(k) is not None]
    return f"{head}: {', '.join(extra)}" if extra else head


def _step_of(o: dict[str, Any]) -> tuple[int, int, str] | None:
    """A `step` event's (done, total, unit) when it is a real fraction of a known unit."""
    try:
        done, total = int(o["done"]), int(o["total"])
    except (KeyError, TypeError, ValueError):
        return None
    unit = o.get("unit")
    if total <= 0 or not 0 <= done <= total or unit not in ("page", "block", "topic"):
        return None
    return done, total, str(unit)


class _Tail:
    def __init__(self) -> None:
        self.offset = 0
        self.buf = b""
        self.units_done = 0
        self.units_total = 0
        self.node: str | None = None
        self.doc: str | None = None
        self.cur: tuple[str, str] | None = None  # the unit running now (from unit_start)
        self.step: tuple[int, int, str] | None = None  # its own count: done, total, unit
        self.message: str | None = None
        self.end: dict[str, Any] | None = None
        # the progress fields last written to the row: an unchanged tick writes nothing
        self.written: tuple[Any, ...] | None = None


class JobRunner:
    def __init__(
        self,
        paths: ProjectPaths,
        store: Store,
        *,
        mode: ProviderMode = "config",
        resume: bool = True,
        python: str | None = None,
        event_handlers: dict[str, Callable[[str, dict[str, Any]], None]] | None = None,
    ) -> None:
        self.paths = paths
        self.store = store
        self.mode: ProviderMode = mode
        self.resume = resume
        self.python = python or sys.executable
        self._lock = threading.RLock()
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._tails: dict[str, _Tail] = {}
        self._kill_at: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._next_prune = 0.0
        # worker log events other than the job lifecycle (module 10: `proposal`, `agent_outcome`)
        # are handed to these in log order; a handler must be idempotent (a resumed worker and
        # an adopted job re-read lines)
        self.event_handlers: dict[str, Callable[[str, dict[str, Any]], None]] = dict(
            event_handlers or {}
        )
        # module 11: an export job's worker cannot write the `export_run` action (no DB
        # access); the supervisor records it, once per job, which moves the override cutoff
        self.event_handlers.setdefault("export_run", self._export_run)

    def _export_run(self, job_id: str, o: dict[str, Any]) -> None:
        from manuallabor.export.pipeline import record_export_run

        payload = o.get("payload")
        if not isinstance(payload, dict):
            return
        record_export_run(self.store, payload, request_id=f"{job_id}:export_run")

    # -- public API (JobRunnerP) ------------------------------------------------------------

    def enqueue(
        self,
        plan: RunPlanIn,
        kind: str = "run",
        files: Sequence[Path] = (),
        request_id: str | None = None,
    ) -> JobInfo:
        """Queue a job. With `request_id` (the mutation that caused it) the call is idempotent:
        a replayed request returns the job it enqueued the first time."""
        if request_id is not None:
            # the store transaction makes check-then-insert atomic; never the runner's lock
            # here (lock order, see `_enqueue`)
            with self.store.tx():
                row = self.store.job_by_request(request_id)
                if row is not None:
                    return self._live(job_info(row))  # its current state, as GET shows it
                return self._enqueue(
                    {**plan.model_dump(mode="json"), "request_id": request_id}, kind, [], None
                )
        saved: list[str] = []
        for f in files:
            f = Path(f)
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            dest = self.paths.uploads / sha / f.name
            if f.resolve() != dest.resolve():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
            saved.append(str(dest))
        return self._enqueue(plan.model_dump(mode="json"), kind, saved, None)

    def enqueue_raw(self, plan: dict[str, Any], kind: str) -> JobInfo:
        """Enqueue a job whose plan is not a `RunPlanIn` (module 10: kind `agent`)."""
        return self._enqueue(plan, kind, [], None)

    def _enqueue(
        self, plan: dict[str, Any], kind: str, files: list[str], resumed_from: str | None
    ) -> JobInfo:
        # Lock order: the runner's lock, then the store's; never the reverse. Callers enqueue
        # inside their own `store.tx()` (the agent pass, the calibration apply), so this path
        # takes no runner lock: the transaction alone makes the row and its plan file appear
        # together, and a tick reads the row only after the commit (review 2, lock order).
        # The same transaction orders the fold check against `_start`'s queued -> running write.
        key = self._plan_key(plan, kind, files) if kind in COLLAPSIBLE else None
        with self.store.tx():
            tail = self.store.queue_tail() if key is not None else None
            if tail is not None and tail["plan_key"] == key:
                # an identical job waits at the queue's tail and has no worker yet: it will plan
                # from the state this job was asked for (design 07 section 18)
                job_id = self.store.add_job(
                    kind=kind, plan=plan, resumed_from=resumed_from, plan_key=key,
                    merged_into=f"job-{tail['n']:06d}",
                )  # fmt: skip
                return self.get(job_id)
            job_id = self.store.add_job(
                kind=kind, plan=plan, resumed_from=resumed_from, plan_key=key
            )
            self._write_spec(job_id, kind, plan, files)
        return self.get(job_id)

    def _write_spec(
        self, job_id: str, kind: str, plan: dict[str, Any], files: Sequence[str]
    ) -> None:
        """The worker's input (inside the caller's transaction, with the row it belongs to)."""
        spec = {"kind": kind, "plan": plan, "files": list(files), "mode": self.mode}
        p = self.paths.job_plan(job_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(spec, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        self.store.update_job(job_id, log_path=str(self.paths.job_log(job_id)))

    def _plan_key(self, plan: dict[str, Any], kind: str, files: Sequence[str]) -> str:
        """Every field of the plan except the request id that caused it, plus kind, files and
        provider mode: two jobs with the same key do the same work."""
        body = {
            "kind": kind,
            "plan": {k: v for k, v in plan.items() if k != "request_id"},
            "files": list(files),
            "mode": self.mode,
        }
        return hashlib.sha256(canonical_json(body)).hexdigest()

    def get(self, job_id: str) -> JobInfo:
        row = self.store.job_row(job_id)
        if row is None:
            raise NotFound(job_id)
        return self._live(job_info(row))

    def list(self, status: set[str] | None = None) -> builtins.list[JobInfo]:
        return [self._live(job_info(r)) for r in self.store.job_rows(status)]

    def _live(self, info: JobInfo) -> JobInfo:
        """Add what lives in memory, not in the row (design 07 section 4.1): the running unit's
        own count, and the file names of a queued or running ingest job. A merged row shows its
        survivor's progress (section 18)."""
        if info.status == "merged":
            return self._mirror(info)
        if info.status not in ("queued", "running"):
            return info
        update: dict[str, Any] = {}
        # no lock: called under a caller's store transaction (lock order, see `_enqueue`); a
        # dict lookup and a tuple read are atomic, and a tick replaces `step` whole
        tail = self._tails.get(info.id)
        step = tail.step if tail is not None else None
        if step is not None and info.status == "running":
            update.update(step_done=step[0], step_total=step[1], step_unit=step[2])
        if info.kind == "ingest_run":
            update["files"] = [Path(f).name for f in self._files_of(info.id)]
        return info.model_copy(update=update) if update else info

    def _mirror(self, info: JobInfo) -> JobInfo:
        row = self.store.job_row(info.merged_into) if info.merged_into else None
        if row is None or row["status"] not in ("queued", "running"):
            return info  # settled in the survivor's own transaction; nothing live to show
        live = self._live(job_info(row))
        return info.model_copy(update={k: getattr(live, k) for k in _MIRRORED})

    def _settle_merged(self, job_id: str) -> None:
        """Give the rows folded into `job_id` its terminal state (call inside the transaction
        that wrote it, so no reader sees the survivor ended and its merged rows pending).

        An `interrupted` survivor (its worker died, and it is not resumed) did not do the work,
        and before section 18 the rows folded into it would have been queued jobs that still
        ran: the oldest of them becomes a queued job again, at its own position, and the others
        fold into it. Done, failed and cancelled survivors hand their outcome over."""
        row = self.store.job_row(job_id)
        if row is None or row["status"] not in TERMINAL:
            return
        if row["status"] == "interrupted":
            merged = self.store.merged_rows(job_id)
            if merged:
                heir = f"job-{merged[0]['n']:06d}"
                self._write_spec(heir, merged[0]["kind"], json.loads(merged[0]["plan"]), [])
                self.store.update_job(heir, status="queued", merged_into=None)
                self.store.repoint_merged(job_id, heir)
                return
        self.store.settle_merged(job_id, {k: row[k] for k in _SETTLED})

    def cancel(self, job_id: str) -> JobInfo:
        with self._lock:
            row = self.store.job_row(job_id)
            if row is None:
                raise NotFound(job_id)
            st = row["status"]
            if st in TERMINAL:
                raise InvalidOp(f"{job_id} is already {st}")
            if st in ("queued", "merged"):
                # a merged row withdraws only itself: its survivor still runs for the others
                with self.store.tx():
                    self.store.update_job(
                        job_id, status="cancelled", finished_at=self.store.now(),
                        cancel_requested=1,
                    )  # fmt: skip
                    self._settle_merged(job_id)
                return self.get(job_id)
            self.store.update_job(job_id, cancel_requested=1)
            self._signal(row["pid"], signal.SIGTERM)
            self._kill_at[job_id] = time.monotonic() + KILL_AFTER
        return self.get(job_id)

    def log(self, job_id: str, after_line: int, limit: int = 500) -> builtins.list[dict[str, Any]]:
        row = self.store.job_row(job_id)
        if row is None:
            raise NotFound(job_id)
        if row["merged_into"]:
            job_id = str(row["merged_into"])  # a merged row has no log: its survivor's is the one
        p = self.paths.job_log(job_id)
        if not p.is_file():
            return []
        out: list[dict[str, Any]] = []
        with open(p, "rb") as f:
            for i, raw in enumerate(f):
                if i < after_line:
                    continue
                if not raw.endswith(b"\n"):
                    break
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                out.append({**obj, "line": i})
                if len(out) >= limit:
                    break
        return out

    def prune(self) -> int:
        """Delete finished job rows older than PRUNE_AFTER beyond the newest PRUNE_KEEP."""
        with self._lock:
            return self.store.prune_jobs(TERMINAL, self.store.clock() - PRUNE_AFTER, PRUNE_KEEP)

    def _maybe_prune(self) -> None:
        now = time.monotonic()
        if now < self._next_prune:
            return
        self._next_prune = now + PRUNE_EVERY
        self.prune()

    def start(self) -> None:
        self._reconcile()
        self._maybe_prune()
        self._stop.clear()
        t = threading.Thread(target=self._loop, name="job-runner", daemon=True)
        self._thread = t
        t.start()

    def stop(self) -> None:
        """Stop supervising. A running worker is NOT killed; the next start adopts it."""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=10)
            self._thread = None

    # -- supervision -------------------------------------------------------------------------

    @staticmethod
    def _signal(pid: int | None, sig: int) -> None:
        if not pid:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), sig)

    def _reconcile(self) -> None:
        with self._lock:
            for row in self.store.job_rows({"running"}):
                job_id = f"job-{row['n']:06d}"
                log = self.paths.job_log(job_id)
                fresh = log.is_file() and (time.time() - log.stat().st_mtime) < ADOPT_MAX_SILENCE
                if _alive(row["pid"]) and fresh:
                    self._tails[job_id] = _Tail()  # adopted: tail the log from the start
                    continue
                tail = _Tail()
                self._read(job_id, tail)
                if tail.end is not None:
                    self._finalize(job_id, tail, None)
                    continue
                with self.store.tx():
                    if row["cancel_requested"]:
                        # the user's Cancel landed before the worker died: cancelled, as
                        # `_finalize` decides it mid-session, so its merged rows are cancelled
                        # too and nothing redoes the work (section 18, re-review finding)
                        self.store.update_job(
                            job_id, status="cancelled", finished_at=self.store.now()
                        )
                        self._settle_merged(job_id)
                        continue
                    self.store.update_job(
                        job_id, status="interrupted", finished_at=self.store.now(),
                        error="worker is gone without a job_end line",
                    )  # fmt: skip
                    plan = json.loads(row["plan"])
                    # a killed `labor run` is the user's to repeat; only serve-owned jobs resume
                    if self.resume and plan.get("origin") != "cli":
                        new = self._enqueue(plan, row["kind"], self._files_of(job_id), job_id)
                        # the rows folded into it finish with the job that redoes the work
                        self.store.repoint_merged(job_id, new.merged_into or new.id)
                    else:
                        self._settle_merged(job_id)
            # defensive: a merged row whose survivor ended or vanished (only a hand edit gets here)
            for row in self.store.job_rows({"merged"}):
                into = row["merged_into"]
                target = self.store.job_row(into) if into else None
                with self.store.tx():  # a promotion and its repoint land together
                    if target is None:
                        self.store.update_job(
                            f"job-{row['n']:06d}", status="interrupted",
                            finished_at=self.store.now(),
                            error=f"merged into {into}, which no longer exists",
                        )  # fmt: skip
                    elif target["status"] in TERMINAL:
                        self._settle_merged(str(into))

    def _files_of(self, job_id: str) -> builtins.list[str]:
        try:
            spec = json.loads(self.paths.job_plan(job_id).read_text(encoding="utf-8"))
            return [str(f) for f in spec.get("files", [])]
        except (OSError, ValueError):
            return []

    def _loop(self) -> None:
        while not self._stop.wait(TICK):
            try:
                self.poll()
                self._maybe_prune()
            except Exception:  # supervision must outlive a bad tick
                import logging

                logging.getLogger(__name__).exception("job runner tick failed")

    def poll(self) -> None:
        """One supervision tick (also called directly by tests)."""
        with self._lock:
            running = self.store.job_rows({"running"})
            still_running = len(running)
            for row in running:
                job_id = f"job-{row['n']:06d}"
                tail = self._tails.setdefault(job_id, _Tail())
                self._read(job_id, tail)
                proc = self._procs.get(job_id)
                gone = (proc.poll() is not None) if proc is not None else not _alive(row["pid"])
                if (
                    job_id in self._kill_at
                    and not gone
                    and time.monotonic() > self._kill_at[job_id]
                ):
                    self._signal(row["pid"], signal.SIGKILL)
                if gone:
                    self._read(job_id, tail)
                    self._finalize(job_id, tail, proc.returncode if proc is not None else None)
                    still_running -= 1
                else:
                    self._update_progress(job_id, tail)
            # rows only change status under this lock (the runner is the single job-row writer;
            # a CLI run holds the project lock, so it cannot run beside serve)
            if not still_running:
                # one row, not every queued row: rows are wider since section 18 (plan_key)
                head = self.store.queue_head()
                if head is not None:
                    self._start(head)

    def _start(self, job_id: str) -> None:
        paths = self.paths
        # `running` before the process exists: a job is only folded into while queued, so no
        # worker that may already be reading its inputs ever absorbs a later change (section 18)
        self.store.update_job(job_id, status="running", started_at=self.store.now())
        try:
            paths.job_log(job_id).parent.mkdir(parents=True, exist_ok=True)
            with open(paths.job_log(job_id).with_suffix(".stderr"), "ab") as err:
                proc = subprocess.Popen(  # noqa: S603
                    [self.python, "-m", "manuallabor.jobs.worker", str(paths.root), job_id],
                    stdout=err,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(paths.root),
                )
        except OSError as exc:
            with self.store.tx():
                self.store.update_job(
                    job_id, status="failed", finished_at=self.store.now(),
                    error=f"could not start the worker: {exc}"[:500],
                )  # fmt: skip
                self._settle_merged(job_id)
            return
        # set before the worker has imported anything: the threads it starts inherit it
        with contextlib.suppress(OSError, AttributeError):
            os.setpriority(os.PRIO_PROCESS, proc.pid, WORKER_NICE)
        self._procs[job_id] = proc
        self._tails[job_id] = _Tail()
        self.store.update_job(job_id, pid=proc.pid)

    def _read(self, job_id: str, tail: _Tail) -> None:
        p = self.paths.job_log(job_id)
        if not p.is_file():
            return
        with open(p, "rb") as f:
            f.seek(tail.offset)
            chunk = f.read()
        tail.offset += len(chunk)
        data = tail.buf + chunk
        *lines, tail.buf = data.split(b"\n")
        for raw in lines:
            if not raw.strip():
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            ev = o.get("event")
            if ev == "job_start":
                tail.units_total = int(o.get("units", 0))
            elif ev == "unit_start":
                tail.node, tail.doc = o.get("node"), o.get("doc")
                tail.cur, tail.step = (str(tail.node), str(tail.doc or "")), None
            elif ev == "step":
                if tail.cur == (str(o.get("node")), str(o.get("doc") or "")):
                    tail.step = _step_of(o) or tail.step
            elif ev == "unit_done":
                tail.units_done += 1
                tail.node, tail.doc = o.get("node"), o.get("doc")
                tail.cur, tail.step = None, None
            elif ev == "job_end":
                tail.end = o
            elif ev in self.event_handlers:
                self.event_handlers[ev](job_id, o)
            elif ev is None:
                msg = _summary(o)
                if msg:
                    tail.message = msg

    def _update_progress(self, job_id: str, tail: _Tail) -> None:
        total = tail.units_total
        fields = (tail.units_done, total, tail.node, tail.doc, tail.message, tail.step)
        if fields == tail.written:
            return  # nothing new in the log since the last write (most ticks)
        inner = 0.0 if tail.step is None else tail.step[0] / tail.step[1]
        prog = 0.0 if total <= 0 else min(1.0, (tail.units_done + inner) / total)
        row = self.store.job_row(job_id)
        if row is not None:
            prog = max(prog, float(row["progress"]))  # monotonic
        self.store.update_job(
            job_id, units_done=tail.units_done, units_total=total, progress=prog,
            node=tail.node, doc=tail.doc, message=tail.message,
        )  # fmt: skip
        tail.written = fields

    def _finalize(self, job_id: str, tail: _Tail, exit_code: int | None) -> None:
        self._update_progress(job_id, tail)
        row = self.store.job_row(job_id)
        assert row is not None
        if tail.end is not None:
            status = str(tail.end.get("status", "failed"))
            error = tail.end.get("error")
            error = None if error is None else str(error)[:500]
            if status == "failed" and not error and tail.end.get("failed"):
                error = f"failed: {json.dumps(tail.end['failed'], sort_keys=True)}"
        elif row["cancel_requested"]:
            status, error = "cancelled", None
        else:
            status, error = "interrupted", "worker exited without a job_end line"
        fields: dict[str, Any] = {"status": status, "finished_at": self.store.now(), "error": error}
        if exit_code is not None:
            fields["exit_code"] = exit_code
        if status == "done":
            fields["progress"] = 1.0
        with self.store.tx():
            self.store.update_job(job_id, **fields)
            self._settle_merged(job_id)
        self._procs.pop(job_id, None)
        self._tails.pop(job_id, None)
        self._kill_at.pop(job_id, None)
