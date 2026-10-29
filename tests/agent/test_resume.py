"""Design 10 test 18: a worker killed mid-pass (MANUALLABOR_FAULT=agent.after_items:2) is
resumed from the same plan; the proposals end up complete and unique per (flag, round)."""

from __future__ import annotations

import json

import pytest

from manuallabor.jobs.runner import JobRunner
from tests.agent.conftest import AEnv
from tests.jobs.test_runner import wait_for


def test_18_killed_worker_is_resumed(aenv: AEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    aenv.seed()
    for ev in ("proposal", "agent_outcome"):
        aenv.runner.event_handlers[ev] = aenv.agent.ingest_event
    monkeypatch.setenv("MANUALLABOR_FAULT", "agent.after_items:2")
    job = aenv.agent.enqueue(None, None, "run-1")
    aenv.runner.poll()  # starts the worker, which kills itself after two items
    proc = aenv.runner._procs[job.id]
    wait_for(lambda: proc.poll() is not None, 120)
    monkeypatch.delenv("MANUALLABOR_FAULT")
    # a new supervisor (a serve restart): the job is `running` with a dead worker
    runner2 = JobRunner(aenv.paths, aenv.store, mode="mock", resume=True)
    for ev in ("proposal", "agent_outcome"):
        runner2.event_handlers[ev] = aenv.agent.ingest_event
    runner2._reconcile()
    assert len(aenv.agent.proposals()) + _outcomes(aenv) == 2  # the two finished items arrived
    old = runner2.get(job.id)
    assert old.status == "interrupted"
    resumed = [j for j in runner2.list() if j.resumed_from == job.id]
    assert len(resumed) == 1
    wait_for(
        lambda: (
            (runner2.poll() or True) and runner2.get(resumed[0].id).status in ("done", "failed")
        ),
        240,
    )
    assert runner2.get(resumed[0].id).status == "done"
    props = aenv.agent.proposals()
    assert len(props) == 5
    assert len({(p.flag_id, p.round) for p in props}) == 5
    assert json.loads(aenv.paths.agent_proposals.read_text())[0]["round"] == 1


def _outcomes(aenv: AEnv) -> int:
    p = aenv.paths.agent_outcomes
    return len(json.loads(p.read_text())) if p.is_file() else 0
