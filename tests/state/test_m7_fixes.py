"""Module 7 review fixes: approve after a human edit keeps the edit; numbers_verified only on
approve; a request id reused for another kind of action is refused."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockStatus, BlockType, DecisionAction
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import RequestIdReused
from manuallabor.state.models import ReviewActionIn, SelectionOp
from manuallabor.state.review import derive
from manuallabor.state.store import sha_text
from tests.conftest import make_block
from tests.state.helpers import Env
from tests.state.test_review import _numeric_block, _pick, rec


@pytest.fixture
def env(lp: ProjectPaths):  # type: ignore[no-untyped-def]
    e = Env(lp)
    yield e
    e.close()


def test_derive_edit_then_approve_is_edited_and_approved() -> None:
    b = make_block("Torque 35 Nm.", status=BlockStatus.queued, clean_text="Torque 35 Nm.")
    b = b.model_copy(update={"has_numeric_spec": True})
    edited = "Torque 36 Nm."
    ed = rec(1, b, DecisionAction.edit, text=edited)
    ap = rec(2, b, DecisionAction.approve, shown=edited)
    r = derive(b, [ed, ap], {})
    assert r.status == BlockStatus.edited and r.decision is ap
    # an approval recorded against other text never discards the human edit
    stale = rec(2, b, DecisionAction.approve, shown="Torque 35 Nm.")
    assert derive(b, [ed, stale], {}).status == BlockStatus.edited


def test_edit_then_approve_approves_the_edited_text(env: Env) -> None:
    nb = _numeric_block(env)
    assert nb.has_numeric_spec
    digit = next(c for c in nb.raw_text if c.isdigit())
    changed = nb.raw_text.replace(digit, str((int(digit) + 1) % 10), 1)
    out = env.act("edit", nb.id, text=changed, confirm_content_change=True)
    assert out.decision is not None and out.decision.numbers_verified is False  # edit: never
    ov = {x.id: x for x in env.blocks(nb.doc_id)}[nb.id]
    assert ov.status == BlockStatus.edited and ov.numbers_verified is False
    assert env.store.numbers_verified_blocks() == []
    # K then A: the approval applies to the edited text
    out = env.act("approve", nb.id)
    assert out.decision is not None and out.decision.decision.action == DecisionAction.approve
    assert out.decision.shown_text_sha256 == sha_text(changed)
    assert out.decision.numbers_verified is True
    assert out.block_status == BlockStatus.edited
    ov = {x.id: x for x in env.blocks(nb.doc_id)}[nb.id]
    assert ov.clean_text == changed  # the human edit is kept
    assert ov.status == BlockStatus.edited and ov.numbers_verified is True
    assert env.store.numbers_verified_blocks() == [nb.id]
    hist = [d.decision.action for d in env.review.detail(nb.id).history]
    assert hist == [DecisionAction.edit, DecisionAction.approve]
    action = [a for a in env.store.iter_actions() if a.target_id == nb.id][-1]
    assert action.example is not None and action.example["clean_after"] == changed


def test_edit_then_approve_without_numbers_does_not_verify(env: Env) -> None:
    b = _pick(
        env,
        lambda b: (
            b.type == BlockType.paragraph
            and not b.has_numeric_spec
            and b.clean_text not in (None, b.raw_text)
        ),
    )
    env.act("edit", b.id, text=b.clean_text)
    out = env.act("approve", b.id)
    assert out.decision is not None and out.decision.numbers_verified is False
    ov = {x.id: x for x in env.blocks(b.doc_id)}[b.id]
    assert ov.status == BlockStatus.edited and ov.clean_text == b.clean_text
    assert ov.numbers_verified is False


def test_request_id_reused_for_another_action_kind_is_refused(env: Env) -> None:
    b = _pick(env, lambda b: b.type == BlockType.paragraph)
    env.review.act(ReviewActionIn(kind="approve", block_id=b.id, request_id="shared"))
    n = env.store.count_actions()
    with pytest.raises(RequestIdReused):
        env.scope.apply(SelectionOp(op="select", block_ids=[], request_id="shared"))
    with pytest.raises(RequestIdReused):
        env.scope.set_project_threshold(0.5, "slider", "shared")
    with pytest.raises(RequestIdReused):
        env.review.resolve_flag("flag-000001", "x", "shared")
    assert env.store.count_actions() == n
    # the same kind replays
    again = env.review.act(ReviewActionIn(kind="approve", block_id=b.id, request_id="shared"))
    assert again.action_id == env.store.max_action_id()
