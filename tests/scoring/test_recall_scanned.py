"""Test 21 (SPEC 11.2): on the scanned fixture, every block whose OCR output differs from the
ground truth has confidence below the threshold."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.scoring.pipeline import load_scored_blocks
from tests.scoring.conftest import Scored

GT = Path(__file__).resolve().parents[1] / "fixtures" / "ground_truth" / "scanned.json"
N3 = re.compile(r"^[ \t]*[^\w\s][ \t]+", re.M)
THRESHOLD = 0.85


def norm(s: str) -> str:
    return " ".join(N3.sub("", unicodedata.normalize("NFC", s)).split())


def test_scanned_recall(scoredproj: Scored) -> None:
    gt = json.loads(GT.read_text())
    pages: dict[int, list[str]] = {}
    for g in gt["blocks"]:
        pages.setdefault(g["page"], []).append(norm("\n".join(g["raw_lines"])))
    gp = {p: " ".join(v) for p, v in pages.items()}
    blocks = [
        b
        for b in load_scored_blocks(scoredproj.paths, "scanned")
        if b.type not in (BlockType.figure, BlockType.header, BlockType.footer)
        and b.raw_text.strip()
    ]
    differs = [b for b in blocks if norm(b.raw_text) not in gp.get(b.page, "")]
    caught = [b for b in differs if b.confidence is not None and b.confidence < THRESHOLD]
    queued = [b for b in differs if b.status == BlockStatus.queued]
    low = sum(1 for b in blocks if b.confidence is not None and b.confidence < THRESHOLD)
    load = sum(1 for b in blocks if b.status == BlockStatus.queued)
    recall = len(caught) / len(differs)
    print(
        f"\nSPEC 11.2 scanned recall {recall:.3f} ({len(caught)}/{len(differs)} differing blocks "
        f"below {THRESHOLD}); queue recall {len(queued)}/{len(differs)}; "
        f"below threshold {low}/{len(blocks)}; review load (queued) {load}/{len(blocks)}"
    )
    missed = [(b.id, b.confidence, b.raw_text[:60]) for b in differs if b not in caught]
    assert len(differs) >= 10
    assert recall >= 0.95, missed
    assert len(queued) == len(differs)
