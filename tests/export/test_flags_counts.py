"""Overrides never swallow a flag, and every count the Export screen shows partitions what it
counts (design 11 section 14: the browser-run findings of 2026-10-30).

1. A block override covers a block's review state only. An open flag is covered by an override
   that names that flag (or a blanket override): a batch of block overrides that included a
   flagged block silently unlocked the export before.
2. `ExportStatus.counts` puts every in-scope block in exactly one bucket and agrees with the
   Verify counts; `ExportSummary.review` puts every exported block in exactly one bucket and
   `left_out` accounts for the rest of the parsed blocks. Before, the summary added the
   all-blocks status counts (page headers included) to the override count: 7 + 1 + 75 + 101 =
   184 against 160 blocks in scope."""

from __future__ import annotations

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from manuallabor.contracts.io import read_json
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.pipeline import export_status, record_override, resolve_clock, run_export
from manuallabor.export.types import GateLocked
from manuallabor.ids import UNASSIGNED
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp
from manuallabor.state.models import ExportStatus, FlagIn, ReviewActionIn, ReviewCounts
from manuallabor.state.store import Store
from tests.export.helpers import CLOCK, reviewer
from tests.export.test_api import Env


def review_counts(paths: ProjectPaths, store: Store) -> ReviewCounts:
    return reviewer(paths, store).queue(None, None, None, 1, 0).counts


def assert_partition(paths: ProjectPaths, store: Store) -> ExportStatus:
    """The gate's counts partition the scope and agree with the Verify counts."""
    st = export_status(paths, store)
    c = st.counts
    assert c is not None
    buckets = c.auto_approved + c.approved + c.edited + c.rejected + c.overridden + c.blocking
    assert buckets == c.in_scope, c
    rc = review_counts(paths, store)
    assert c.in_scope == rc.in_scope, (c, rc)
    assert (c.auto_approved, c.approved, c.edited, c.rejected) == (
        rc.auto_approved,
        rc.approved,
        rc.edited,
        rc.rejected,
    ), (c, rc)
    assert c.overridden + c.blocking == rc.queued + rc.flagged_open, (c, rc)
    assert (c.blocking == 0) == (st.blockers == [])
    assert len(st.blockers) == min(c.blocking, 20)
    assert len(st.flag_blockers) <= c.blocking
    return st


def override_all(paths: ProjectPaths, store: Store, reason: str, skip: set[str]) -> None:
    """What the Export screen does: one block override per listed blocker, page by page."""
    for _ in range(100):
        st = export_status(paths, store)
        todo = [b for b in st.blockers if b not in skip]
        if not todo:
            return
        for b in todo:
            record_override(paths, store, reason, target_id=b, request_id=f"t-ov-{b}")
    raise AssertionError("overrides did not converge")


def flag_block(paths: ProjectPaths, store: Store, block_id: str) -> str:
    out = reviewer(paths, store).act(
        ReviewActionIn(
            kind="flag",
            block_id=block_id,
            flag=FlagIn(category="wrong_text", note="digit unclear"),
            request_id=f"t-flag-{block_id}",
        )
    )
    assert out.flag is not None
    return out.flag.id


# -- defect 1: a flag needs its own decision ---------------------------------------------------


def test_a_block_override_batch_never_covers_an_open_flag(unreviewed: ProjectPaths) -> None:
    store = Store.open(unreviewed)
    try:
        st = export_status(unreviewed, store)
        flagged = st.blockers[1]
        fid = flag_block(unreviewed, store, flagged)
        st = assert_partition(unreviewed, store)
        assert [(f.flag_id, f.block_id) for f in st.flag_blockers] == [(fid, flagged)]
        assert st.flag_blockers[0].category == "wrong_text"
        assert st.flag_blockers[0].note == "digit unclear"
        # a block override on the flagged block is refused: it would bypass the flag
        with pytest.raises(InvalidOp, match=fid):
            record_override(unreviewed, store, "batch", target_id=flagged)
        override_all(unreviewed, store, "batch", skip={flagged})
        st = assert_partition(unreviewed, store)
        assert st.blockers == [flagged] and st.counts is not None and st.counts.blocking == 1
        with pytest.raises(GateLocked):
            run_export(unreviewed, store, clock=resolve_clock(CLOCK))
        # the flag's own override is the explicit decision that unlocks it
        record_override(unreviewed, store, "checked on paper", flag_id=fid)
        st = assert_partition(unreviewed, store)
        assert st.blockers == [] and st.flag_blockers == []
        rec = run_export(unreviewed, store, clock=resolve_clock(CLOCK))
    finally:
        store.close()
    m = read_json(unreviewed.assembled / "manifest.json", Manifest)
    (mine,) = [o for o in m.overrides if o.target_id == flagged]
    assert mine.flag_id == fid and mine.reason == "checked on paper"
    assert rec.summary.review.overrides == len(m.overrides)


def test_a_flag_raised_before_a_block_override_still_blocks(unreviewed: ProjectPaths) -> None:
    """The refusal is not the only guard: the gate itself never lets a block override cover a
    flag, whatever the order (a block override recorded before the flag was raised)."""
    store = Store.open(unreviewed)
    try:
        b = export_status(unreviewed, store).blockers[0]
        record_override(unreviewed, store, "batch", target_id=b)
        assert b not in export_status(unreviewed, store).blockers
        fid = flag_block(unreviewed, store, b)
        st = export_status(unreviewed, store)
        assert b in st.blockers and [f.flag_id for f in st.flag_blockers] == [fid]
    finally:
        store.close()


def test_the_override_route_refuses_a_block_override_on_a_flagged_block(
    unreviewed: ProjectPaths,
) -> None:
    env = Env(unreviewed)
    try:
        c: TestClient = env.client
        b = c.get("/api/export/status").json()["blockers"][0]
        store = env.ctx.store
        assert isinstance(store, Store)
        fid = flag_block(unreviewed, store, b)
        st = c.get("/api/export/status").json()
        assert st["flag_blockers"] == [
            {"flag_id": fid, "block_id": b, "category": "wrong_text", "note": "digit unclear"}
        ]
        r = c.post(
            "/api/export/override", json={"reason": "x", "target_id": b, "request_id": "rq-b"}
        )
        assert r.status_code == 422 and fid in r.json()["detail"]
        ok = c.post(
            "/api/export/override", json={"reason": "x", "flag_id": fid, "request_id": "rq-f"}
        )
        assert ok.status_code == 200
        assert b not in ok.json()["blockers"] and ok.json()["flag_blockers"] == []
    finally:
        env.close()


# -- defect 2: the counts partition ------------------------------------------------------------


def test_status_counts_partition_the_scope_unreviewed_then_partly_reviewed(
    unreviewed: ProjectPaths,
) -> None:
    store = Store.open(unreviewed)
    try:
        st = assert_partition(unreviewed, store)
        assert st.counts is not None and st.counts.blocking > 0
        first, second, third = st.blockers[:3]
        reviewer(unreviewed, store).act(
            ReviewActionIn(kind="approve", block_id=first, request_id="t-a1")
        )
        flag_block(unreviewed, store, second)
        record_override(unreviewed, store, "r", target_id=third)
        before = st.counts
        st = assert_partition(unreviewed, store)
        assert st.counts is not None
        assert st.counts.approved == before.approved + 1
        assert st.counts.overridden == before.overridden + 1
        assert st.counts.blocking == before.blocking - 2  # the flagged one still blocks
    finally:
        store.close()


def test_status_counts_partition_the_scope_reviewed(work: ProjectPaths) -> None:
    store = Store.open(work)
    try:
        st = assert_partition(work, store)
        assert st.counts is not None and st.counts.blocking == 0 and st.unlocked
    finally:
        store.close()


def test_status_counts_partition_the_scope_with_duplicate_figures(
    scored_dup: ProjectPaths,
) -> None:
    store = Store.open(scored_dup, readonly=True)
    try:
        assert_partition(scored_dup, store)
    finally:
        store.close()


def test_the_summary_partitions_the_exported_blocks_after_an_override_export(
    unreviewed: ProjectPaths,
) -> None:
    """Dana's export: a few approvals, everything else overridden, then export."""
    store = Store.open(unreviewed)
    try:
        st = export_status(unreviewed, store)
        for i, b in enumerate(st.blockers[:2]):
            reviewer(unreviewed, store).act(
                ReviewActionIn(kind="approve", block_id=b, request_id=f"t-ap-{i}")
            )
        override_all(unreviewed, store, "pilot", skip=set())
        before = assert_partition(unreviewed, store).counts
        assert before is not None and before.blocking == 0 and before.overridden > 0
        rec = run_export(unreviewed, store, clock=resolve_clock(CLOCK))
        after = assert_partition(unreviewed, store)
    finally:
        store.close()
    s = rec.summary.review
    m = read_json(unreviewed.assembled / "manifest.json", Manifest)
    exported = [b for b, a in m.accounting.assignments.items() if a != UNASSIGNED]
    assert s.blocks == len(exported) == s.auto_approved + s.approved + s.edited + s.overrides
    assert s.total_blocks == m.accounting.total_blocks == s.blocks + sum(s.left_out.values())
    assert s.left_out == dict(Counter(m.accounting.unassigned_reasons.values()))
    # page headers and footers are left out, never counted as auto-approved
    assert s.auto_approved == before.auto_approved and s.approved == before.approved
    assert s.overrides == before.overridden == len(m.overrides)
    assert s.blocks == before.in_scope - before.rejected
    # the export spent its overrides (P3): the same blocks block a new export, and the
    # summary of the export just made is still there to show and download
    assert after.counts is not None and after.counts.blocking == before.overridden
    assert after.summary == rec.summary
