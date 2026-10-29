"""Child processes of the kill tests (`python -m tests.jobs.children <what> ...`)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def review_actions(root: str, n_ok: int, fault: str) -> None:
    """Apply n_ok review actions (printing each outcome), then one more under a fault."""
    from manuallabor.project import ProjectPaths
    from manuallabor.state.models import ReviewActionIn
    from tests.state.helpers import Env

    env = Env(ProjectPaths(Path(root)))
    page = env.review.queue(None, None, None, n_ok + 2, 0)
    for i, item in enumerate(page.items[: n_ok + 1]):
        if i == n_ok:
            os.environ["MANUALLABOR_FAULT"] = fault
        out = env.review.act(
            ReviewActionIn(kind="approve", block_id=item.block_id, request_id=f"c-{i}")
        )
        print(
            json.dumps({"action_id": out.action_id, "cursor": out.cursor.model_dump(mode="json")}),
            flush=True,
        )


def selection_ops(root: str, fault: str) -> None:
    from manuallabor.project import ProjectPaths
    from manuallabor.state.models import SelectionOp
    from tests.state.helpers import Env

    env = Env(ProjectPaths(Path(root)))
    ids = sorted(env.data.selection().block_ids)
    env.scope.apply(SelectionOp(op="deselect", block_ids=ids[:2], request_id="o1"))
    print("first", flush=True)
    os.environ["MANUALLABOR_FAULT"] = fault
    env.scope.apply(SelectionOp(op="deselect", block_ids=ids[2:5], request_id="o2"))
    print("unreachable", flush=True)


def supervisor(root: str, mode: str, enqueue: str) -> None:
    """A stand-in for `labor serve`: owns the store, runs the JobRunner, prints job events."""
    from manuallabor.jobs.runner import JobRunner
    from manuallabor.project import ProjectPaths
    from manuallabor.state.lock import ProjectLock
    from manuallabor.state.models import RunPlanIn
    from manuallabor.state.store import Store

    paths = ProjectPaths(Path(root))
    lock = ProjectLock(paths.lock, cmd="supervisor")
    lock.acquire()
    store = Store.open(paths)
    runner = JobRunner(paths, store, mode="mock" if mode == "mock" else "config", resume=True)
    runner.start()
    if enqueue == "yes":
        job = runner.enqueue(RunPlanIn(to="score2"))
        print(json.dumps({"enqueued": job.id}), flush=True)
    print("ready", flush=True)
    while True:
        time.sleep(0.2)


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "review":
        review_actions(sys.argv[2], int(sys.argv[3]), sys.argv[4])
    elif what == "selection":
        selection_ops(sys.argv[2], sys.argv[3])
    elif what == "supervisor":
        supervisor(sys.argv[2], sys.argv[3], sys.argv[4])
