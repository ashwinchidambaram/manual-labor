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
from pathlib import Path
from typing import Any

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


class _Tail:
    def __init__(self) -> None:
        self.offset = 0
        self.buf = b""
        self.units_done = 0
        self.units_total = 0
        self.node: str | None = None
        self.doc: str | None = None
        self.message: str | None = None
        self.end: dict[str, Any] | None = None


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
            with self._lock:
                for row in self.store.job_rows():
                    if json.loads(row["plan"]).get("request_id") == request_id:
                        return job_info(row)
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
        with self._lock, self.store.tx():
            job_id = self.store.add_job(kind=kind, plan=plan, resumed_from=resumed_from)
            spec = {"kind": kind, "plan": plan, "files": files, "mode": self.mode}
            p = self.paths.job_plan(job_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(spec, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            self.store.update_job(job_id, log_path=str(self.paths.job_log(job_id)))
        return self.get(job_id)

    def get(self, job_id: str) -> JobInfo:
        row = self.store.job_row(job_id)
        if row is None:
            raise NotFound(job_id)
        return job_info(row)

    def list(self, status: set[str] | None = None) -> builtins.list[JobInfo]:
        return [job_info(r) for r in self.store.job_rows(status)]

    def cancel(self, job_id: str) -> JobInfo:
        with self._lock:
            row = self.store.job_row(job_id)
            if row is None:
                raise NotFound(job_id)
            st = row["status"]
            if st in TERMINAL:
                raise InvalidOp(f"{job_id} is already {st}")
            if st == "queued":
                self.store.update_job(
                    job_id, status="cancelled", finished_at=self.store.now(), cancel_requested=1
                )
                return self.get(job_id)
            self.store.update_job(job_id, cancel_requested=1)
            self._signal(row["pid"], signal.SIGTERM)
            self._kill_at[job_id] = time.monotonic() + KILL_AFTER
        return self.get(job_id)

    def log(self, job_id: str, after_line: int, limit: int = 500) -> builtins.list[dict[str, Any]]:
        if self.store.job_row(job_id) is None:
            raise NotFound(job_id)
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

    def start(self) -> None:
        self._reconcile()
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
                self.store.update_job(
                    job_id, status="interrupted", finished_at=self.store.now(),
                    error="worker is gone without a job_end line",
                )  # fmt: skip
                plan = json.loads(row["plan"])
                # a killed `labor run` is the user's to repeat; only serve-owned jobs resume
                if self.resume and not row["cancel_requested"] and plan.get("origin") != "cli":
                    self._enqueue(plan, row["kind"], self._files_of(job_id), job_id)

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
            except Exception:  # supervision must outlive a bad tick
                import logging

                logging.getLogger(__name__).exception("job runner tick failed")

    def poll(self) -> None:
        """One supervision tick (also called directly by tests)."""
        with self._lock:
            for row in self.store.job_rows({"running"}):
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
                else:
                    self._update_progress(job_id, tail)
            if not self.store.job_rows({"running"}):
                queued = self.store.job_rows({"queued"})
                if queued:
                    self._start(f"job-{queued[0]['n']:06d}")

    def _start(self, job_id: str) -> None:
        paths = self.paths
        paths.job_log(job_id).parent.mkdir(parents=True, exist_ok=True)
        err = open(paths.job_log(job_id).with_suffix(".stderr"), "ab")  # noqa: SIM115
        proc = subprocess.Popen(  # noqa: S603
            [self.python, "-m", "manuallabor.jobs.worker", str(paths.root), job_id],
            stdout=err,
            stderr=err,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(paths.root),
        )
        err.close()
        self._procs[job_id] = proc
        self._tails[job_id] = _Tail()
        self.store.update_job(job_id, status="running", pid=proc.pid, started_at=self.store.now())

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
            elif ev == "unit_done":
                tail.units_done += 1
                tail.node, tail.doc = o.get("node"), o.get("doc")
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
        prog = 0.0 if total <= 0 else min(1.0, tail.units_done / total)
        row = self.store.job_row(job_id)
        if row is not None:
            prog = max(prog, float(row["progress"]))  # monotonic
        self.store.update_job(
            job_id, units_done=tail.units_done, units_total=total, progress=prog,
            node=tail.node, doc=tail.doc, message=tail.message,
        )  # fmt: skip

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
        self.store.update_job(job_id, **fields)
        self._procs.pop(job_id, None)
        self._tails.pop(job_id, None)
        self._kill_at.pop(job_id, None)
