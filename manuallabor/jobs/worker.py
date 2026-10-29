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
from pathlib import Path
from typing import Any

from manuallabor.contracts.enums import Task
from manuallabor.jobs.executor import Cancelled, Heartbeat, Plan, execute, make_plan
from manuallabor.jobs.providers import provider_set_factory
from manuallabor.project import ProjectPaths
from manuallabor.providers.sinks import JsonlSink
from manuallabor.state.errors import LockHeld
from manuallabor.state.lock import ProjectLock

EXIT_LOCK = 3
BEAT_SECONDS = 5.0
BEAT_MIN_INTERVAL = 0.5


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
    status, failed, error = "done", {}, None
    try:
        rp = spec["plan"]
        if spec.get("kind") == "ingest_run":
            from manuallabor.ingest import ingest_files

            provider = providers().get(Task.metadata) if mode == "mock" else None
            ingest_files(
                paths,
                [Path(f) for f in spec.get("files", [])],
                provider=provider,
                emit=lambda o: log({**o, "node": "ingest"}),
            )
        plan: Plan = make_plan(
            paths,
            paths.load_config(),
            to=rp.get("to", "score2"),
            docs=rp.get("docs"),
            force=set(rp.get("force", [])),
            allow_reparse=bool(rp.get("allow_reparse", False)),
            provider_mode=mode,
        )
        log({"event": "job_start", "units": len(plan.units)})
        res = execute(
            paths, plan, emit=log, providers=providers, cancelled=cancel.is_set, heartbeat=hb
        )
        failed = {**res.failed, **({"plan": [s for s, _ in res.refused]} if res.refused else {})}
        if failed:
            status = "failed"
    except Cancelled:
        status = "cancelled"
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        _close_pools()
        log({"event": "job_end", "status": status, "failed": failed, "error": error})
        log.close()
        wlock.release()
    return 0 if status == "done" else (130 if status == "cancelled" else 1)


def _close_pools() -> None:
    """The OCR pool is closed by parse's own `finally`; nothing else to release here."""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m manuallabor.jobs.worker <project root> <job id>", file=sys.stderr)
        return 2
    return run_job(Path(argv[0]), argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
