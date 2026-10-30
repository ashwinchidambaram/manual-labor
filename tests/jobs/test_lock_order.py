"""One lock order between the job runner and the store (backend review 2, pre-existing finding).

`AgentService.enqueue` and `CalibrationService.apply` enqueue a job inside `store.tx()` (store
lock, then the runner's lock), while the supervisor tick takes the runner's lock and then the
store's for each query. A tick that lands while an agent pass is being enqueued deadlocked both
threads, and with them every later API request. The rule: the runner's lock is never taken
while the store's is held; the enqueue path relies on the store transaction alone."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store

ENQUEUES: dict[str, Callable[[JobRunner], Any]] = {
    "enqueue_raw (agent pass)": lambda r: r.enqueue_raw({"items": []}, "agent"),
    "enqueue (calibration apply)": lambda r: r.enqueue(RunPlanIn(to="score2")),
    "enqueue with a request id": lambda r: r.enqueue(RunPlanIn(to="score2"), request_id="rq-1"),
}


@pytest.mark.parametrize("name", sorted(ENQUEUES))
def test_enqueue_inside_a_transaction_beside_a_tick_does_not_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    paths = ProjectPaths(tmp_path / "proj")
    paths.root.mkdir(parents=True)
    store = Store.open(paths)
    runner = JobRunner(paths, store, mode="mock", resume=False)
    started: list[str] = []
    monkeypatch.setattr(runner, "_start", started.append)  # never spawn a worker here
    in_tick = threading.Event()
    real_rows = store.job_rows

    def job_rows(*a: Any, **k: Any) -> Any:
        in_tick.set()  # the tick holds the runner's lock and is about to wait for the store's
        return real_rows(*a, **k)

    monkeypatch.setattr(store, "job_rows", job_rows)
    done: dict[str, Any] = {"tx": False, "tick": False}

    def tx_side() -> None:
        with store.tx():  # what AgentService.enqueue / CalibrationService.apply do
            assert in_tick.wait(10)
            in_tick.clear()
            threading.Event().wait(0.2)  # let the tick block on the store lock
            done["job"] = ENQUEUES[name](runner).id
        done["tx"] = True

    def tick_side() -> None:
        runner.poll()
        done["tick"] = True

    a = threading.Thread(target=tx_side, daemon=True)
    a.start()
    b = threading.Thread(target=tick_side, daemon=True)
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)
    assert done["tx"] and done["tick"], f"deadlock: {done}"
    # the tick's first query waited for the commit, so it saw the new job and started it
    assert started == [done["job"]]
    store.close()
