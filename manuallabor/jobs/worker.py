"""Job worker: `python -m manuallabor.jobs.worker <project root> <job id>` (design 07 section 4).

No DB access: it takes the worker lock, reads `logs/jobs/<id>.plan.json`, runs the executor
and writes NDJSON progress to `logs/jobs/<id>.jsonl` (flushed per line). The supervisor
(JobRunner, in the serve process) turns those lines into job rows. SIGTERM requests a cancel,
honoured at the next unit or LLM call. The `__main__` guard is required: parse spawns an OCR
pool."""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from manuallabor import faults
from manuallabor.contracts.enums import Task
from manuallabor.jobs import progress
from manuallabor.jobs.executor import (
    PROJECT_NODES,
    Cancelled,
    Heartbeat,
    Plan,
    execute,
    make_plan,
    make_project_plan,
)
from manuallabor.jobs.providers import provider_set_factory
from manuallabor.project import ProjectPaths
from manuallabor.providers.sinks import JsonlSink
from manuallabor.state.errors import LockHeld
from manuallabor.state.lock import ProjectLock

EXIT_LOCK = 3
BEAT_SECONDS = 5.0
BEAT_MIN_INTERVAL = 0.5
STEP_MIN_INTERVAL = 0.25


class JobLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8", newline="\n")  # noqa: SIM115
        self._lock = threading.Lock()

    def __call__(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self.f.write(line + "\n")
            self.f.flush()

    def close(self) -> None:
        self.f.close()


class StepLog:
    """The job log as the executor's `emit`, plus what the jobs bar needs (design 07 section 4.1):
    a `unit_start` line before each planned unit runs, and `step` lines with a stage's own count
    of pages, blocks or topics done within the current unit (`progress.report`). Step lines are
    written at most every `STEP_MIN_INTERVAL` seconds (the first and the last count always), never
    go backwards, and are dropped when they do not belong to the current unit."""

    def __init__(
        self,
        log: Callable[[dict[str, Any]], None],
        units: Sequence[tuple[str, str]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.log = log
        self.units = list(units)
        self.clock = clock
        self.i = -1  # index of the current unit; -1 before job_start
        self.cur: tuple[str, str] | None = None
        self._last_t = float("-inf")
        self._last_done = -1
        self._lock = threading.Lock()

    def _start(self, i: int) -> None:
        self.i = i
        self.cur = self.units[i] if i < len(self.units) else None
        self._last_t, self._last_done = float("-inf"), -1
        if self.cur is not None:
            node, doc = self.cur
            self.log({"event": "unit_start", "node": node, "doc": doc, "index": i})

    def _ended(self, node: Any, doc: Any) -> None:
        """The unit (node, doc) ended: start the planned unit after it."""
        key = (str(node), str(doc or ""))
        for j in range(max(self.i, 0), len(self.units)):
            if self.units[j] == key:
                self._start(j + 1)
                return

    def __call__(self, obj: dict[str, Any]) -> None:
        with self._lock:
            self.log(obj)
            ev = obj.get("event")
            if ev == "job_start":
                self._start(0)
            elif ev == "unit_done":
                self._ended(obj.get("node"), obj.get("doc"))
            elif (
                ev is None
                and obj.get("status") == "blocked"
                and obj.get("doc")
                and self.cur == (str(obj.get("node")), str(obj.get("doc")))
            ):
                # a blocked document unit writes no unit_done; a project-level unit (doc "")
                # always does, so it ends there, not at its blocked line (review 2 finding 7)
                self._ended(obj["node"], obj.get("doc"))

    def step(self, doc: str, done: int, total: int, unit: progress.StepUnit) -> None:
        with self._lock:
            if self.cur is None or self.cur[1] != doc or done < self._last_done:
                return
            node = self.cur[0]
            now = self.clock()
            last = done == total
            if done == self._last_done or (not last and now - self._last_t < STEP_MIN_INTERVAL):
                return
            self._last_t, self._last_done = now, done
            self.log(
                {"event": "step", "node": node, "doc": doc, "done": done, "total": total,
                 "unit": unit}
            )  # fmt: skip
        faults.delay(f"step:{node}")  # e2e: a unit that is visibly still counting


def run_job(root: Path, job_id: str) -> int:
    paths = ProjectPaths(root)
    spec = json.loads(paths.job_plan(job_id).read_text(encoding="utf-8"))
    log = JobLog(paths.job_log(job_id))
    wlock = ProjectLock(paths.worker_lock, cmd=f"worker {job_id}")
    try:
        wlock.acquire()
    except LockHeld as exc:
        log({"event": "job_end", "status": "failed", "error": str(exc), "failed": {}})
        log.close()
        return EXIT_LOCK
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    cfg = paths.load_config()
    mode = spec.get("mode", "config")
    stop = threading.Event()
    last_beat = [0.0]
    calls = [0]

    def beat(n: int) -> None:
        calls[0] = n
        now = time.monotonic()
        if now - last_beat[0] >= BEAT_MIN_INTERVAL:
            last_beat[0] = now
            log({"event": "heartbeat", "llm_calls": n})

    def pulse() -> None:
        while not stop.wait(BEAT_SECONDS):
            log({"event": "heartbeat", "llm_calls": calls[0]})

    threading.Thread(target=pulse, daemon=True).start()
    hb = Heartbeat(JsonlSink(paths.llm_log), on_beat=beat, cancelled=cancel.is_set)
    providers = provider_set_factory(paths, cfg, mode, hb)
    status, error = "done", None
    failed: dict[str, Any] = {}
    try:
        rp = spec["plan"]
        if spec.get("kind") == "agent":
            from manuallabor.agent.pipeline import run_agent_plan

            n_err = run_agent_plan(paths, rp, providers, log, cancel.is_set)
            if n_err:
                status, error = "failed", f"{n_err} agent item(s) ended in an error"
        else:
            status, failed, error = _run_stages(paths, spec, rp, mode, providers, log, hb, cancel)
    except Cancelled:
        status = "cancelled"
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
    finally:
        stop.set()
        _close_pools()
        log({"event": "job_end", "status": status, "failed": failed, "error": error})
        log.close()
        wlock.release()
    return 0 if status == "done" else (130 if status == "cancelled" else 1)


def _run_stages(
    paths: ProjectPaths,
    spec: dict[str, Any],
    rp: dict[str, Any],
    mode: str,
    providers: Any,
    log: JobLog,
    hb: Heartbeat,
    cancel: threading.Event,
) -> tuple[str, dict[str, Any], str | None]:
    """The stage-graph job body (`run` and `ingest_run`)."""
    status = "done"
    failed: dict[str, Any] = {}
    if spec.get("kind") == "ingest_run":
        from manuallabor.ingest import ingest_files

        provider = providers().get(Task.metadata) if mode == "mock" else None
        ingest_files(
            paths,
            [Path(f) for f in spec.get("files", [])],
            provider=provider,
            emit=lambda o: log({**o, "node": "ingest"}),
        )
    cfg = paths.load_config()
    kwargs: dict[str, Any] = {
        "docs": rp.get("docs"),
        "force": set(rp.get("force", [])),
        "allow_reparse": bool(rp.get("allow_reparse", False)),
        "provider_mode": mode,
    }
    plan: Plan = (
        make_project_plan(paths, cfg, to=rp["to"], **kwargs)
        if rp.get("to") in PROJECT_NODES
        else make_plan(paths, cfg, to=rp.get("to", "score2"), **kwargs)
    )
    steps = StepLog(log, plan.units)
    steps({"event": "job_start", "units": len(plan.units)})
    prev = progress.set_reporter(steps.step)
    try:
        res = execute(
            paths, plan, emit=steps, providers=providers, cancelled=cancel.is_set, heartbeat=hb
        )
    finally:
        progress.set_reporter(prev)
    failed = {**res.failed, **({"plan": [s for s, _ in res.refused]} if res.refused else {})}
    if failed:
        status = "failed"
    return status, failed, res.error_message() if failed else None


def _close_pools() -> None:
    """The OCR pool is closed by parse's own `finally`; nothing else to release here."""


def main(argv: list[str]) -> int:
    from manuallabor.providers.offline import install_from_env

    install_from_env()  # MANUALLABOR_OFFLINE=1: no network but the local model server
    if len(argv) != 2:
        print("usage: python -m manuallabor.jobs.worker <project root> <job id>", file=sys.stderr)
        return 2
    return run_job(Path(argv[0]), argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
