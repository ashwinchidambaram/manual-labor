"""Module 12 review: the review counts reconcile from independently derived fields.

``queued`` and ``rejected`` are counted from each block's derived status (not computed as
in_scope minus the other buckets), so the UI's reconciliation line can actually fail."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.project import ProjectPaths
from manuallabor.state.review import load_review_blocks
from tests.api.test_real_services import serving

BUCKETS = ("queued", "auto_approved", "approved", "edited", "flagged_open", "rejected")


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


def _reject(rejected: set[str], real: Callable[..., list[Block]]) -> Callable[..., list[Block]]:
    """The machine blocks with ``rejected`` forced to status rejected (no pipeline stage emits
    it today; the counts must still place it in its own bucket)."""

    def load(paths: ProjectPaths, slug: str) -> list[Block]:
        out = []
        for b in real(paths, slug):
            if b.id in rejected:
                b = Block.model_validate(
                    {**b.model_dump(mode="json"), "status": BlockStatus.rejected.value}
                )
            out.append(b)
        return out

    return load


def _status_derived(svc: Any, paths: ProjectPaths) -> Counter[str]:
    """Counts straight from the per-block status derivation over the in-scope blocks."""
    data = svc.review.data
    selected = set(data.selection().block_ids)
    n: Counter[str] = Counter()
    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        if not (dp.scores.is_file() and dp.clean.is_file()):
            continue
        scope = data.scope_ids(slug, selected)
        for b in load_review_blocks(paths, svc.store, slug):
            if b.id not in scope or b.type in (BlockType.header, BlockType.footer):
                continue
            n["in_scope"] += 1
            n[b.status.value] += 1
    return n


def test_counts_are_independently_derived_and_reconcile(
    lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serving(lp) as (c, _svc):
        before = c.get("/api/verify/queue?limit=1000").json()
        text = [
            i["block_id"]
            for i in before["items"]
            if i["type"] != "figure" and i["status"] == "queued"
        ]
    assert len(text) >= 7
    a0, a1, f0, f1, e0, r0, r1 = text[:7]
    c0 = before["counts"]
    assert c0["rejected"] == 0 and c0["queued"] >= 7

    import manuallabor.scoring.pipeline as sp
    import manuallabor.state.data as sd

    patched = _reject({r0, r1}, sp.load_scored_blocks)
    monkeypatch.setattr(sp, "load_scored_blocks", patched)
    monkeypatch.setattr(sd, "load_scored_blocks", patched)

    with serving(lp) as (c, svc):

        def act(rid: str, kind: str, bid: str, **kw: Any) -> None:
            body = {"kind": kind, "block_id": bid, "request_id": rid, **kw}
            r = c.post("/api/verify/actions", json=body)
            assert r.status_code == 200, r.text

        act("c1", "approve", a0)
        act("c2", "approve", a1)
        act("c3", "flag", f0, flag={"category": "wrong_text", "note": "n"})
        act("c4", "flag", f1, flag={"category": "missing_figure"})
        blk = c.get(f"/api/verify/blocks/{e0}").json()["block"]
        shown = blk["clean_text"] if blk["clean_text"] is not None else blk["raw_text"]
        act("c5", "edit", e0, text=shown)

        counts = c.get("/api/verify/queue?limit=1000").json()["counts"]
        expected = _status_derived(svc, lp)

    # every bucket equals the status-derived number
    assert counts["in_scope"] == expected["in_scope"]
    assert counts["queued"] == expected[BlockStatus.queued.value]
    assert counts["rejected"] == expected[BlockStatus.rejected.value] == 2
    assert counts["approved"] == expected[BlockStatus.approved.value]
    assert counts["edited"] == expected[BlockStatus.edited.value]
    assert counts["flagged_open"] == expected[BlockStatus.flagged.value]
    assert counts["auto_approved"] == expected[BlockStatus.auto_approved.value]
    # the seeded moves, against the first snapshot
    assert counts["approved"] == c0["approved"] + 2
    assert counts["flagged_open"] == c0["flagged_open"] + 2
    assert counts["edited"] == c0["edited"] + 1
    assert counts["queued"] == c0["queued"] - 7
    assert counts["in_scope"] == c0["in_scope"]
    # the reconciliation holds from independent fields (rejected is no longer a hidden hole)
    assert sum(counts[k] for k in BUCKETS) == counts["in_scope"]
    assert sum(c0[k] for k in BUCKETS) == c0["in_scope"]
