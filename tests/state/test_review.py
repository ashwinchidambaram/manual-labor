"""S4-S8: status derivation, human edits, numeric approve, queue, the 20-action key script."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.enums import (
    BlockStatus,
    BlockType,
    DecisionAction,
    FlagCategory,
    FlagStatus,
)
from manuallabor.contracts.flag import Flag
from manuallabor.project import ProjectPaths
from manuallabor.scoring.queue import build_queue
from manuallabor.state.errors import EditConflictError, InvalidOp, OutOfScope
from manuallabor.state.models import (
    DecisionRecord,
    FlagIn,
    QueueSort,
    SelectionOp,
)
from manuallabor.state.review import (
    derive,
    derive_status,
    display_text,
)
from manuallabor.state.store import Store, sha_text
from tests.conftest import make_block
from tests.state.helpers import Env

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def rec(
    seq: int,
    block: Block,
    action: DecisionAction,
    *,
    raw: str | None = None,
    shown: str | None = None,
    flag_id: str | None = None,
    text: str | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        decision=Decision(
            seq=seq,
            block_id=block.id,
            action=action,
            score=block.confidence,
            threshold=0.85,
            signals=[],
            edited_text=text if action == DecisionAction.edit else None,
            flag_id=flag_id,
            timestamp=NOW,
        ),
        action_id=seq,
        doc_id=block.doc_id,
        raw_sha256=sha_text(raw if raw is not None else block.raw_text),
        shown_text_sha256=sha_text(shown if shown is not None else display_text(block)),
        faith_passed=True if action == DecisionAction.edit else None,
        numbers_verified=False,
    )


def flag(n: int, status: FlagStatus) -> Flag:
    return Flag(
        id=f"flag-{n:06d}",
        target_id="b-doc-p001-01",
        category=FlagCategory.wrong_text,
        status=status,
        created_at=NOW,
        resolved_at=NOW if status == FlagStatus.resolved else None,
    )


def test_s4_status_table() -> None:
    b = make_block(
        "Check the drive belt.", status=BlockStatus.queued, clean_text="Check the drive belt."
    )
    open_f, done_f = flag(1, FlagStatus.open), flag(2, FlagStatus.resolved)
    flags = {open_f.id: open_f, done_f.id: done_f}
    # no decision: the machine status
    assert derive_status(b, [], flags) == (BlockStatus.queued, None)
    auto = b.model_copy(update={"status": BlockStatus.auto_approved})
    assert derive_status(auto, [], flags) == (BlockStatus.auto_approved, None)
    # approve of the text that is shown now
    assert derive_status(b, [rec(1, b, DecisionAction.approve)], flags)[0] == BlockStatus.approved
    # approve of text that has changed since (cleanup / learning re-run)
    changed = rec(1, b, DecisionAction.approve, shown="an older clean text")
    assert derive_status(b, [changed], flags) == (BlockStatus.queued, "changed since approval")
    # edit
    ed = rec(2, b, DecisionAction.edit, text="Check the drive belt!")
    assert derive_status(b, [rec(1, b, DecisionAction.approve), ed], flags)[0] == BlockStatus.edited
    # skip is ignored
    assert derive_status(b, [rec(1, b, DecisionAction.skip)], flags)[0] == BlockStatus.queued
    sk = [rec(1, b, DecisionAction.approve), rec(2, b, DecisionAction.skip)]
    assert derive_status(b, sk, flags)[0] == BlockStatus.approved
    # flag: open -> flagged, resolved -> machine status
    assert derive_status(b, [rec(1, b, DecisionAction.flag, flag_id=open_f.id)], flags)[0] == (
        BlockStatus.flagged
    )
    assert derive_status(b, [rec(1, b, DecisionAction.flag, flag_id=done_f.id)], flags)[0] == (
        BlockStatus.queued
    )
    # a decision made on other raw text (re-parse) is stale and ignored, and counted
    r = derive(b, [rec(1, b, DecisionAction.approve, raw="the old raw text")], flags)
    assert r.status == BlockStatus.queued and r.orphaned == 1


@pytest.fixture
def env(lp: ProjectPaths):  # type: ignore[no-untyped-def]
    e = Env(lp)
    yield e
    e.close()


def _pick(env: Env, pred) -> Block:  # type: ignore[no-untyped-def]
    page = env.review.queue(None, None, None, 5000, 0)
    for item in page.items:
        for b in env.blocks(item.doc_id):
            if b.id == item.block_id and pred(b):
                return b
    raise AssertionError("no block matches")


def test_s4_service_flag_resolution_and_stale_approval(env: Env) -> None:
    b = _pick(env, lambda b: b.type == BlockType.paragraph)
    out = env.act("flag", b.id, flag=FlagIn(category=FlagCategory.wrong_text, note="smudge"))
    assert out.block_status == BlockStatus.flagged and out.flag is not None
    assert env.store.open_flag_count() == 1
    ov = {x.id: x for x in env.blocks(b.doc_id)}[b.id]
    assert ov.status == BlockStatus.flagged
    out = env.act("approve", b.id)  # approve resolves the open flag in the same transaction
    assert out.block_status == BlockStatus.approved
    assert env.store.open_flag_count() == 0
    resolved = env.store.get_flag(out.decision.decision.flag_id or "flag-000001")
    assert resolved is not None and resolved.status == FlagStatus.resolved
    assert resolved.resolution is not None and resolved.resolution.startswith("superseded by")
    # the shown text changes (a re-clean): the approval does not transfer
    from manuallabor.cleanup.types import CleanFile
    from manuallabor.contracts.io import read_json, write_json

    cf = read_json(env.paths.doc(b.doc_id).clean, CleanFile)
    entries = [
        e.model_copy(update={"clean_text": e.clean_text + " "}) if e.block_id == b.id else e
        for e in cf.blocks
    ]
    write_json(env.paths.doc(b.doc_id).clean, cf.model_copy(update={"blocks": entries}))
    from manuallabor.state.data import sig  # noqa: F401

    d = env.review.detail(b.id)
    assert d.block.status in (BlockStatus.queued, BlockStatus.auto_approved)
    assert any(w.kind == "stale" and w.name == "changed since approval" for w in d.why)


def _numeric_block(env: Env) -> Block:
    return _pick(
        env,
        lambda b: (
            b.type == BlockType.paragraph
            and any(ch.isdigit() for ch in b.raw_text)
            and b.raw_text == b.raw_text.strip()
        ),
    )


def test_s5_human_edit_goes_through_the_faithfulness_check(env: Env) -> None:
    # a lossless edit (the machine's own clean text) passes
    b = _pick(
        env, lambda b: b.type == BlockType.paragraph and b.clean_text not in (None, b.raw_text)
    )
    out = env.act("edit", b.id, text=b.clean_text)
    assert out.decision is not None and out.decision.faith_passed is True
    assert out.block_status == BlockStatus.edited
    # changing a number conflicts, and writes nothing
    nb = _numeric_block(env)
    digit = next(c for c in nb.raw_text if c.isdigit())
    changed = nb.raw_text.replace(digit, str((int(digit) + 1) % 10), 1)
    n = env.store.count_actions()
    with pytest.raises(EditConflictError) as ei:
        env.act("edit", nb.id, text=changed)
    assert ei.value.conflict.numeric_changes and "→" in ei.value.conflict.numeric_changes[0]
    assert env.store.count_actions() == n
    # with the confirmation it is stored, recorded as a human content change
    out = env.act("edit", nb.id, text=changed, confirm_content_change=True)
    assert out.decision is not None and out.decision.faith_passed is False
    assert out.decision.human_edit_diff
    assert any(d.op.value in ("replace", "insert", "delete") for d in out.decision.human_edit_diff)
    ov = {x.id: x for x in env.blocks(nb.doc_id)}[nb.id]
    assert ov.status == BlockStatus.edited and ov.clean_text == changed
    Block.model_validate(ov.model_dump(mode="json"))
    action = [a for a in env.store.iter_actions() if a.target_id == nb.id][-1]
    assert action.example is not None and action.example["human_edit"] is True
    assert action.after_ref is not None and env.store.get_blob(action.after_ref) == changed
    # empty text and figure blocks are refused
    with pytest.raises(InvalidOp):
        env.act("edit", b.id, text="   ")
    fig = _pick(env, lambda b: b.type == BlockType.figure)
    with pytest.raises(InvalidOp):
        env.act("edit", fig.id, text="x")


def test_s5_out_of_scope_is_refused(env: Env) -> None:
    sel = env.data.selection().block_ids
    victim = next(b for b in sel if b.startswith("b-clean-"))
    env.scope.apply(SelectionOp(op="deselect", block_ids=[victim], request_id=env.rid()))
    with pytest.raises(OutOfScope):
        env.act("approve", victim)


def test_s6_numeric_approve_sets_numbers_verified(env: Env) -> None:
    nb = _pick(env, lambda b: b.has_numeric_spec and b.type == BlockType.paragraph)
    assert env.store.numbers_verified_blocks() == []
    out = env.act("approve", nb.id)
    assert out.decision is not None and out.decision.numbers_verified is True
    ov = {x.id: x for x in env.blocks(nb.doc_id)}[nb.id]
    assert ov.numbers_verified is True and ov.status == BlockStatus.approved
    assert env.store.numbers_verified_blocks() == [nb.id]
    other = _pick(env, lambda b: not b.has_numeric_spec and b.type == BlockType.paragraph)
    out = env.act("approve", other.id)
    assert out.decision is not None and out.decision.numbers_verified is False
    third = _pick(env, lambda b: b.has_numeric_spec and b.type == BlockType.paragraph)
    env.act("skip", third.id)
    assert third.id not in env.store.numbers_verified_blocks()
    # a re-parse (raw text changed) drops the verification
    assert env.store.numbers_verified_blocks({nb.id: "other raw text"}) == []


def _scope_ids(env: Env) -> set[str]:
    sel = set(env.data.selection().block_ids)
    out: set[str] = set()
    for s in env.paths.list_slugs():
        out |= env.data.scope_ids(s, sel)
    return out


def test_s7_queue_orders_and_threshold_is_a_view(env: Env) -> None:
    scope = _scope_ids(env)
    machine = {b.id: b for s in env.paths.list_slugs() for b in env.data.machine_blocks(s)}
    expected = [i for i in build_queue(machine.values()) if i in scope]
    page = env.review.queue(QueueSort.worst_first, None, None, 5000, 0)
    assert [i.block_id for i in page.items] == expected
    assert page.total == len(expected) == page.counts.pending
    by_page = env.review.queue(QueueSort.by_page, None, None, 5000, 0)
    assert [i.block_id for i in by_page.items] == sorted(expected, key=ids.block_sort_key)
    figs = env.review.queue(QueueSort.figures_only, None, None, 5000, 0)
    assert figs.items and all(i.type == BlockType.figure for i in figs.items)
    # the slider is a view filter: it only adds undecided auto-approved blocks
    n_actions = env.store.count_actions()
    wide = env.review.queue(None, 1.0, None, 5000, 0)
    auto = [
        i
        for i, b in machine.items()
        if i in scope
        and b.status == BlockStatus.auto_approved
        and b.confidence is not None
        and b.confidence < 1.0
    ]
    assert wide.total == len(expected) + len(auto)
    assert {i.block_id for i in wide.items} >= set(expected)
    none = env.review.queue(None, 0.0, None, 5000, 0)
    assert [i.block_id for i in none.items] == expected  # machine-queued blocks stay listed
    assert env.store.count_actions() == n_actions  # reading creates no decisions
    # setting the view threshold on the cursor records history but no decisions
    from manuallabor.state.models import Cursor

    env.review.set_cursor(Cursor(view_threshold=0.9), env.rid())
    rows = env.store.q("SELECT * FROM threshold_history")
    assert len(rows) == 1 and rows[0]["kind"] == "view" and rows[0]["new"] == 0.9
    assert env.store.decisions() == []
    assert env.review.queue(None, None, None, 5000, 0).cursor.view_threshold == 0.9
    # paging
    p1 = env.review.queue(None, None, None, 7, 0)
    p2 = env.review.queue(None, None, None, 7, 7)
    assert [i.block_id for i in p1.items + p2.items] == expected[:14]


def test_s8_keyboard_script_next_cursor_back_wrap(env: Env) -> None:
    scope = _scope_ids(env)
    machine = {b.id: b for s in env.paths.list_slugs() for b in env.data.machine_blocks(s)}
    pending = [i for i in build_queue(machine.values()) if i in scope]

    def key(i: str) -> tuple[float, tuple[str, int, int]]:
        c = machine[i].confidence
        return (-1.0 if c is None else c, ids.block_sort_key(i))

    def expected_next(after: str) -> str | None:
        if not pending:
            return None
        ahead = [i for i in pending if key(i) > key(after)]
        return ahead[0] if ahead else pending[0]

    # editable (paragraph) blocks and one figure, in queue order
    cur = pending[0]
    trail: list[str] = []
    script = list("AAEFJKAEAJ") + list(
        "AAFEJKAAEA"
    )  # A approve, E edit (lossless), F flag, J/K skip, ...
    for k in script:
        b = machine[cur]
        if k == "E" and b.type != BlockType.paragraph:
            k = "A"
        text = b.raw_text if k == "E" and b.clean_text in (None, b.raw_text) else b.clean_text
        kw: dict[str, object] = {}
        if k == "A":
            kind = "approve"
        elif k == "E":
            kind, kw = "edit", {"text": text}
        elif k == "F":
            kind, kw = "flag", {"flag": FlagIn(category=FlagCategory.wrong_text)}
        else:
            kind = "skip"
        out = env.act(kind, cur, **kw)
        if kind != "skip":
            pending.remove(cur)
        want = expected_next(cur)
        assert (out.next.block_id if out.next else None) == want, (k, cur)
        trail.append(cur)
        assert out.cursor.current_block_id == want
        assert out.cursor.trail == trail[-50:]
        assert out.counts.pending == len(pending)
        if want is None:
            break
        cur = want
    # back pops the trail and records no decision
    n_dec = len(env.store.decisions())
    out = env.act("back")
    last = trail.pop()
    assert out.cursor.current_block_id == last and out.cursor.trail == trail
    assert out.decision is None and len(env.store.decisions()) == n_dec
    # reopening returns the stored cursor verbatim
    stored = env.review.cursor()
    env.close()
    again = Env(env.paths)
    try:
        assert again.review.cursor() == stored == out.cursor
    finally:
        again.close()
    env.store = Store.open(env.paths)  # let the fixture close something valid
