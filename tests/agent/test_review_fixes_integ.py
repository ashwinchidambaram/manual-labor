"""Module 10 review fixes over a real project: the accept race, the staleness basis and the
completeness of the check list at accept."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from manuallabor.agent.errors import AgentConflict
from manuallabor.agent.inputs import basis_sha256
from manuallabor.api.app import create_app
from manuallabor.api.deps import Hooks
from manuallabor.calibration.apply import CalibrationService
from manuallabor.contracts.enums import FlagStatus, ProposalKind, ProposalStatus
from manuallabor.state.data import ProjectData
from manuallabor.state.interfaces import AppServices
from manuallabor.state.learning import LearningService
from manuallabor.state.review import display_text, load_review_blocks
from tests.agent.conftest import AEnv
from tests.agent.test_accept import forge


@pytest.fixture
def client(aenv: AEnv) -> Iterator[TestClient]:
    svc = AppServices(
        paths=aenv.paths,
        store=aenv.store,
        review=aenv.review,
        scope=aenv.scope,
        figures=aenv.figures,
        learning=LearningService(aenv.paths, aenv.store),
        runner=aenv.runner,
        mock=True,
        agent=aenv.agent,
        calibration=CalibrationService(aenv.paths, aenv.store, aenv.data, aenv.runner),
    )
    with TestClient(create_app(svc, hooks=Hooks())) as c:
        yield c


def _race(client: TestClient, pid: str) -> list[tuple[int, str]]:
    res: list[tuple[int, str]] = []
    bar = threading.Barrier(2)

    def go(i: int) -> None:
        bar.wait()
        r = client.post(f"/api/agent/proposals/{pid}/accept", json={"request_id": f"race-{i}"})
        body = r.json()
        res.append((r.status_code, body["status"] if r.status_code == 200 else body["code"]))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return sorted(res)


def _slow_fresh(aenv: AEnv) -> None:
    """Both requests pass the checks made before the transaction, then both try to apply."""
    orig = aenv.agent._fresh

    def slow(p: Any) -> bool:
        ok = orig(p)
        time.sleep(0.3)
        return ok

    aenv.agent._fresh = slow  # type: ignore[method-assign]


@pytest.mark.parametrize("slow", [True, False])
def test_concurrent_accept_of_an_attach_applies_once(
    aenv: AEnv, client: TestClient, slow: bool
) -> None:
    aenv.seed([2])  # missing_figure -> an attach proposal that passes its checks
    aenv.run_agent()
    (p,) = aenv.agent.proposals()
    assert p.kind == ProposalKind.attach and p.all_checks_passed
    jobs_before = len(aenv.store.job_rows())
    if slow:
        _slow_fresh(aenv)
    res = _race(client, p.id)
    assert res[0] == (200, "accepted")
    assert res[1][0] == 409
    if slow:
        assert res[1][1] == "already_decided"
    else:
        assert res[1][1] in ("already_decided", "not_pending")
    acts = [a for a in aenv.store.iter_actions() if (a.payload or {}).get("proposal_id") == p.id]
    assert len(acts) == 1
    assert len(aenv.store.overrides("attach_overrides")) == 1
    assert len(aenv.store.job_rows()) == jobs_before + 1
    assert aenv.agent.proposal(p.id).status == ProposalStatus.accepted


def test_concurrent_accept_of_a_text_proposal_records_one_decision(
    aenv: AEnv, client: TestClient
) -> None:
    (f,) = aenv.seed([1])
    blk = next(b for b in aenv.data.machine_blocks("figures") if b.id == "b-figures-p006-03")
    p = forge(aenv, f, blk.raw_text + " extra")
    _slow_fresh(aenv)
    res = _race(client, p.id)
    assert res == [(200, "accepted"), (409, "already_decided")]
    agent = [d for d in aenv.store.decisions() if d.source == "agent"]
    assert len(agent) == 1
    assert aenv.store.get_flag(f).status == FlagStatus.resolved  # type: ignore[union-attr]


def test_accept_refuses_an_incomplete_check_list(aenv: AEnv) -> None:
    (f,) = aenv.seed([1])
    blk = next(b for b in aenv.data.machine_blocks("figures") if b.id == "b-figures-p006-03")
    p = forge(aenv, f, blk.raw_text + " extra", checks=["shape"])
    assert not p.all_checks_passed
    with pytest.raises(AgentConflict) as ei:
        aenv.agent.accept(p.id, "r-acc")
    assert ei.value.code == "checks_failed" and "missing" in ei.value.detail
    assert aenv.agent.accept_all_passing(None, "bulk") == []


def test_basis_covers_has_numeric_spec(aenv: AEnv) -> None:
    bid = "b-figures-p006-03"
    blk = next(b for b in load_review_blocks(aenv.paths, aenv.store, "figures") if b.id == bid)
    cur = display_text(blk)
    b0 = basis_sha256(aenv.paths, aenv.data, bid, ProposalKind.text, cur, None)
    sf = aenv.paths.doc("figures").scores
    sd = json.loads(sf.read_text())
    flipped = None
    for s in sd["blocks"]:
        if s["block_id"] == bid:
            s["has_numeric_spec"] = flipped = not s["has_numeric_spec"]
    sf.write_text(json.dumps(sd))
    data = ProjectData(aenv.paths, aenv.store)
    mb = next(b for b in data.machine_blocks("figures") if b.id == bid)
    assert mb.has_numeric_spec is flipped
    assert basis_sha256(aenv.paths, data, bid, ProposalKind.text, cur, None) != b0


def test_attach_basis_covers_the_topic_view(aenv: AEnv) -> None:
    bid = "b-clean-p004-04"
    b0 = basis_sha256(aenv.paths, aenv.data, bid, ProposalKind.attach, None, None)
    gp = aenv.paths.doc("clean").groups
    gp.write_bytes(gp.read_bytes() + b"\n")
    assert basis_sha256(aenv.paths, aenv.data, bid, ProposalKind.attach, None, None) != b0
