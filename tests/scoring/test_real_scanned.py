"""Test 23 (live-only): the real scanned manual (tests/fixtures/real). Numeric-token recall on
the ground-truth sample: every GT numeric token that the pipeline did not read verbatim must sit
in a region whose blocks are all queued for review.

Skips unless real-manual.pdf and ground_truth_sample.json exist and MANUALLABOR_LIVE=1 (it OCRs
the 7 GT pages, which is too slow for the fast suite)."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.figures.pipeline import run_figures
from manuallabor.ingest import ingest_files
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import load_scored_blocks, run_score

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "real"
PDF = REAL / "real-manual.pdf"
GT = REAL / "ground_truth_sample.json"
PROJECT_JSON = Path(__file__).resolve().parents[1] / "fixtures" / "project-a" / "project.json"
STRIP = ".,;:()"


def num_tokens(text: str) -> list[str]:
    """The GT file's numeric_token_rule."""
    out = []
    for t in text.split():
        t = t.strip(STRIP)
        if any(c.isdigit() for c in t):
            out.append(t)
    return out


def coverage(a: list[float], b: list[float]) -> float:
    """Intersection over the smaller box: 1.0 when one box lies inside the other."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def region(blocks: list[Block], g: dict[str, Any], page: int) -> list[Block]:
    """Blocks (figures included: chart text stays inside the figure crop) that lie mostly inside
    the approximate GT box or cover most of it; a block that only grazes it is not its region."""
    return [
        b
        for b in blocks
        if b.page == page and b.bbox is not None and coverage(list(b.bbox), g["bbox"]) >= 0.5
    ]


@pytest.mark.skipif(
    not (PDF.is_file() and GT.is_file()) or os.environ.get("MANUALLABOR_LIVE") != "1",
    reason="live-only: needs tests/fixtures/real/real-manual.pdf and MANUALLABOR_LIVE=1",
)
def test_real_manual_numeric_recall(requires_docling: None, tmp_path: Path) -> None:
    from manuallabor.figures.mu import pymupdf

    gt = json.loads(GT.read_text())
    pages = sorted({b["page"] for b in gt["blocks"]})
    src = pymupdf.open(str(PDF))
    sample = pymupdf.open()
    for p in pages:
        sample.insert_pdf(src, from_page=p - 1, to_page=p - 1)
    pdf = tmp_path / "real-sample.pdf"
    sample.save(str(pdf))
    sample.close()
    src.close()
    page_map = {p: i + 1 for i, p in enumerate(pages)}

    root = tmp_path / "proj"
    root.mkdir()
    shutil.copyfile(PROJECT_JSON, root / "project.json")
    paths = ProjectPaths(root)
    ingest_files(paths, [pdf], emit=lambda _o: None)
    assert parse_project(paths, emit=lambda _o: None) == 0
    assert run_figures(paths, emit=lambda _o: None) == []
    assert run_score(paths, emit=lambda _o: None) == []
    slug = paths.list_slugs()[0]
    blocks = load_scored_blocks(paths, slug)

    total = read_ok = misread = caught = in_figure = 0
    blocks_numeric = blocks_queued = 0
    misses: list[tuple[str, str]] = []
    for g in gt["blocks"]:
        toks = [t.strip(STRIP) for t in g["numeric_tokens"]]
        if not toks:
            continue
        reg = region(blocks, g, page_map[g["page"]])
        have = Counter(t for b in reg for t in num_tokens(b.raw_text))
        all_queued = bool(reg) and all(b.status == BlockStatus.queued for b in reg)
        blocks_numeric += 1
        blocks_queued += all_queued
        for t in toks:
            total += 1
            if have[t] > 0:
                have[t] -= 1
                read_ok += 1
                continue
            misread += 1
            if all_queued:
                caught += 1
                in_figure += all(b.type == BlockType.figure for b in reg)
            else:
                misses.append((g["id"], t))
    recall = caught / misread if misread else 1.0
    print(
        f"\nreal manual (7 GT pages): {total} GT numeric tokens, {read_ok} read verbatim, "
        f"{misread} misread/missing, {caught} of those in fully queued regions "
        f"({in_figure} inside queued figure crops) -> recall "
        f"{recall:.3f}; GT numeric blocks fully queued {blocks_queued}/{blocks_numeric}; "
        f"misses {misses}"
    )
    assert recall >= 0.95, misses
