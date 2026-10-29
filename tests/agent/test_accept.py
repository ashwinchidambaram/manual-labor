"""Design 10 tests 5, 9, 16: what accepting records, the vision reader's isolation and the
determinism of the pass."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from manuallabor.agent.errors import AgentConflict
from manuallabor.agent.inputs import basis_sha256
from manuallabor.contracts.enums import (
    BlockStatus,
    FlagStatus,
    ProposalKind,
    ProposalStatus,
    Task,
)
from manuallabor.contracts.proposal import Proposal
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import EditConflictError
from manuallabor.state.models import ActionKind
from manuallabor.state.review import display_text, load_review_blocks
from tests.agent.conftest import AEnv
from tests.conftest import labor_copy


def forge(aenv: AEnv, flag_id: str, text: str) -> Proposal:
    """A pending text proposal whose checks all passed (scaffolding for the accept path; the
    model path is covered by the rechecks' own tests)."""
    flag = aenv.store.get_flag(flag_id)
    assert flag is not None
    slug = flag.target_id.split("-")[1]
    blk = next(
        b for b in load_review_blocks(aenv.paths, aenv.store, slug) if b.id == flag.target_id
    )
    cur = display_text(blk)
    n = aenv.store.next_proposal_n()
    p = Proposal.model_validate(
        {
            "id": f"prop-{n:06d}",
            "flag_id": flag_id,
            "target_id": flag.target_id,
            "round": 1,
            "kind": "text",
            "proposal_text": text,
            "evidence": [{"source": "note", "span": "seeded", "verified": True}],
            "rationale": "forged",
            "rechecks": [{"check": "shape", "passed": True}],
            "basis_sha256": basis_sha256(
                aenv.paths, aenv.data, flag.target_id, ProposalKind.text, cur, None
            ),
            "model": "mock/mock-1",
            "input_hash": "a" * 64,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    with aenv.store.tx():
        aenv.store.add_proposal(p)
    return p


def test_5_accept_records_an_agent_edit(aenv: AEnv) -> None:
    (f,) = aenv.seed([0])
    blk = next(b for b in aenv.data.machine_blocks("clean") if b.id == "b-clean-p002-04")
    assert blk.has_numeric_spec
    p = forge(aenv, f, blk.raw_text.replace("M8", "M9", 1))  # a content change
    out = aenv.agent.accept(p.id, "r-acc")
    assert out.status == ProposalStatus.accepted
    (d,) = [d for d in aenv.store.decisions() if d.source == "agent"]
    assert d.decision.action.value == "edit" and d.faith_passed is False
    assert d.human_edit_diff and d.numbers_verified
    act = aenv.store.get_action(d.action_id)
    assert act is not None and act.kind == ActionKind.proposal_accept and act.screen == "agent"
    assert act.example is not None and act.example["proposal"]["id"] == p.id
    assert aenv.store.get_flag(f).status == FlagStatus.resolved  # type: ignore[union-attr]
    ov = next(b for b in load_review_blocks(aenv.paths, aenv.store, "clean") if b.id == blk.id)
    assert ov.status == BlockStatus.edited and ov.clean_text == p.proposal_text
    assert aenv.store.proposal_row_action(p.id) == d.action_id
    # replaying the request changes nothing
    n = aenv.store.count_actions()
    assert aenv.agent.accept(p.id, "r-acc").id == p.id and aenv.store.count_actions() == n


def test_accept_is_stale_when_the_reviewer_changed_the_block(aenv: AEnv) -> None:
    (f,) = aenv.seed([0])
    blk = next(b for b in aenv.data.machine_blocks("clean") if b.id == "b-clean-p002-04")
    p = forge(aenv, f, blk.raw_text + " extra")
    aenv.review.act(  # a human edit of the same block changes what the checks saw
        __import__("manuallabor.state.models", fromlist=["x"]).ReviewActionIn(
            kind="edit",
            block_id=blk.id,
            text=blk.raw_text + " other",
            request_id="h1",
            confirm_content_change=True,
        )
    )
    # the human decision resolved the flag and superseded the proposal
    assert aenv.agent.proposal(p.id).status == ProposalStatus.superseded
    with pytest.raises(AgentConflict) as ei:
        aenv.agent.accept(p.id, "r-acc")
    assert ei.value.code == "not_pending"


def test_stale_basis_supersedes(aenv: AEnv) -> None:
    (f,) = aenv.seed([0])
    blk = next(b for b in aenv.data.machine_blocks("clean") if b.id == "b-clean-p002-04")
    p = forge(aenv, f, blk.raw_text + " extra")
    # corrupt the stored basis: as if the readers' text changed after the proposal was made
    stale = p.model_copy(update={"basis_sha256": "f" * 64})
    with aenv.store.tx():
        aenv.store.set_proposal(stale, None)
    with pytest.raises(AgentConflict) as ei:
        aenv.agent.accept(p.id, "r-acc")
    assert ei.value.code == "stale_proposal"
    assert aenv.agent.proposal(p.id).status == ProposalStatus.superseded


def test_human_edit_of_a_proposal(aenv: AEnv) -> None:
    (f,) = aenv.seed([0])
    blk = next(b for b in aenv.data.machine_blocks("clean") if b.id == "b-clean-p002-04")
    p = forge(aenv, f, blk.raw_text + " x")
    with pytest.raises(EditConflictError):
        aenv.agent.edit(
            p.id, text=blk.raw_text + " y", bbox=None, confirm_content_change=False, request_id="e1"
        )
    out = aenv.agent.edit(
        p.id, text=blk.raw_text + " y", bbox=None, confirm_content_change=True, request_id="e2"
    )
    assert out.status == ProposalStatus.edited and out.final_text == blk.raw_text + " y"
    (d,) = [d for d in aenv.store.decisions() if d.decision.action.value == "edit"]
    assert d.source == "human"
    act = aenv.store.get_action(d.action_id)
    assert act is not None and act.kind == ActionKind.proposal_edit


def test_9_vision_reader_never_touches_scores(aenv: AEnv) -> None:
    aenv.seed([0])
    scores = {s: (aenv.paths.doc(s).scores).read_bytes() for s in ("clean", "figures")}
    aenv.run_agent(vision=lambda _img, _prompt: "10 to 60 N·m\n35 N·m")
    (p,) = aenv.agent.proposals()
    assert p.vision is not None and p.vision.outcome == "ok"
    assert "35" in p.vision.numbers
    assert not [f for f in p.vision.model_dump() if "conf" in f or "score" in f]
    for s, b in scores.items():
        assert aenv.paths.doc(s).scores.read_bytes() == b
    assert not any(
        "vision" in str(x)
        for x in json.loads(aenv.paths.doc("clean").scores.read_text())["blocks"][0]["signals"]
    )


def test_9_vision_invalid_and_error(aenv: AEnv) -> None:
    aenv.seed([0])
    aenv.run_agent(vision=lambda _i, _p: "x" * 60)
    (p,) = aenv.agent.proposals()
    assert p.vision is not None and p.vision.outcome == "invalid" and p.vision.numbers == []


def copy_seeded(project_a: Path, tmp_path: Path, name: str) -> AEnv:
    e = AEnv(ProjectPaths(labor_copy(project_a, tmp_path / name)))
    e.seed()
    return e


def test_16_deterministic_across_copies(project_a: Path, tmp_path: Path) -> None:
    a, b = copy_seeded(project_a, tmp_path, "a"), copy_seeded(project_a, tmp_path, "b")
    try:
        a.run_agent()
        b.run_agent()
        for name in ("proposals.json", "outcomes.json"):
            pa, pb = a.paths.agent / name, b.paths.agent / name
            if pa.exists() or pb.exists():
                assert pa.read_bytes() == pb.read_bytes()
        assert a.paths.agent_proposals.is_file()
        # a second run creates nothing: every flag has a pending proposal
        plan, skips = a.agent.plan(None, None)
        assert plan.items == [] and {s.outcome for s in skips} == {"pending"}
        # re-asking the same questions is answered from the cache
        n_calls = len(a.sink)
        item_plan, _ = a.agent.plan(None, None)
        assert item_plan.items == []
        from manuallabor.agent.inputs import eligible_items

        items, _s = eligible_items(
            a.paths, a.store, a.data, a.paths.load_config(), include_pending=True
        )
        assert len(items) == 5
        from manuallabor.agent.pipeline import run_agent_plan
        from manuallabor.agent.types import AgentPlan

        run_agent_plan(
            a.paths,
            AgentPlan(items=items).model_dump(mode="json"),
            lambda: a.providers(),
            lambda _o: None,
            lambda: False,
        )
        new = [c for c in a.sink[n_calls:] if c.task == Task.agent]
        assert new and all(c.cached for c in new)
    finally:
        a.close()
        b.close()
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_proposals_json_is_a_projection_of_the_table(aenv: AEnv) -> None:
    aenv.seed([0, 2])
    aenv.run_agent()
    f = aenv.paths.agent_proposals
    want = f.read_text()
    f.unlink()
    from manuallabor.state.projections import reconcile

    reconcile(aenv.store, aenv.paths)
    assert f.read_text() == want
    assert hashlib.sha256(want.encode()).hexdigest()
