"""Test 24: fixture baseline on the scored project."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockStatus, BlockType, SignalName
from manuallabor.scoring.pipeline import load_scored_blocks
from tests.scoring.conftest import Scored

ALL = ("clean", "figures", "manual", "scanned", "tables", "twocol")
BODY_EXCLUDED = (BlockType.header, BlockType.footer)


@pytest.mark.parametrize("slug", ALL)
def test_baseline(scoredproj: Scored, slug: str) -> None:
    blocks = load_scored_blocks(scoredproj.paths, slug)
    for b in blocks:
        if b.type != BlockType.figure:
            f = next(s for s in b.signals if s.name == SignalName.faithfulness)
            assert f.value == 1.0 and f.critical and f.detail == "raw (no cleanup yet)"
        if b.has_numeric_spec:
            assert b.status == BlockStatus.queued
        if slug == "tables" and b.type == BlockType.table:
            assert b.status == BlockStatus.queued and b.has_numeric_spec
        body_text = b.type not in (*BODY_EXCLUDED, BlockType.figure)
        if slug in ("clean", "twocol") and body_text and not b.has_numeric_spec:
            assert b.status == BlockStatus.auto_approved, (b.id, b.signals)
    body = [b for b in blocks if b.type not in BODY_EXCLUDED]
    queued = sum(1 for b in body if b.status == BlockStatus.queued)
    numeric = sum(1 for b in body if b.has_numeric_spec)
    print(
        f"\n{slug}: review load at 0.85 {queued}/{len(body)} = {queued / len(body):.0%} "
        f"({numeric} numeric, {queued - numeric} by score)"
    )
