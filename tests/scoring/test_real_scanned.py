"""Test 23 (live-only): the real scanned manual (tests/fixtures/real), with the same metric as
test 21 (SPEC 11.2): every block whose OCR output differs from the ground truth must have
confidence below the threshold.

The GT is a 20-block sample, so the metric runs per GT block:
- region = the non-figure blocks on that page that lie mostly inside the approximate GT box or
  cover most of it (bbox coverage >= 0.5). Figure blocks never "catch" text: text swallowed by
  a figure crop is a silent drop, so such a GT block has an empty region and counts as a miss;
- the region's text (blocks in reading order) differs from the GT text when the GT token
  sequence is not a contiguous run of the region's tokens. Tokens are the comparison tokens of
  design 2.0 (NFKC, dehyphenation, bullets stripped, casefold), punctuation-only tokens (dot
  leaders, which the GT omits) dropped, and the measured OCR glyph allowances folded
  (`·`/en/em dash -> `-`, `±` -> `+`, curly quotes -> straight);
- a differing GT block is caught when every region block that carries a differing token
  (aligned with SequenceMatcher; region text outside the GT span is ignored) has
  confidence < threshold.
recall = caught / differing; asserted >= 0.95.

Skips unless real-manual.pdf and ground_truth_sample.json exist and MANUALLABOR_LIVE=1 (it OCRs
the 7 GT pages, which is too slow for the fast suite)."""

from __future__ import annotations

import json
import os
import shutil
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.figures.pipeline import run_figures
from manuallabor.ingest import ingest_files
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import load_scored_blocks, run_score
from manuallabor.scoring.text import cmp_tokens

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "real"
PDF = REAL / "real-manual.pdf"
GT = REAL / "ground_truth_sample.json"
PROJECT_JSON = Path(__file__).resolve().parents[1] / "fixtures" / "project-a" / "project.json"
THRESHOLD = 0.85
OCR_GLYPH_FOLD = str.maketrans(
    {"·": "-", "–": "-", "—": "-", "±": "+", "’": "'", "‘": "'", "“": '"', "”": '"'}
)


def tokens(text: str) -> list[str]:
    return [t.translate(OCR_GLYPH_FOLD) for t in cmp_tokens(text) if any(c.isalnum() for c in t)]


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
    """Non-figure blocks that lie mostly inside the approximate GT box or cover most of it."""
    reg = [
        b
        for b in blocks
        if b.page == page
        and b.type != BlockType.figure
        and b.bbox is not None
        and coverage(list(b.bbox), g["bbox"]) >= 0.5
    ]
    return sorted(reg, key=lambda b: b.reading_order)


def contains(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def differing_owners(reg: list[Block], gt_tokens: list[str]) -> set[int]:
    """Indices (into reg) of the blocks that carry a token differing from the GT."""
    rt: list[str] = []
    own: list[int] = []
    for bi, b in enumerate(reg):
        t = tokens(b.raw_text)
        rt += t
        own += [bi] * len(t)
    ops = SequenceMatcher(None, gt_tokens, rt, autojunk=False).get_opcodes()
    equal = [k for k, op in enumerate(ops) if op[0] == "equal"]
    out: set[int] = set()
    for k, (tag, _i1, _i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        if tag == "insert" and (not equal or k < equal[0] or k > equal[-1]):
            continue  # region text before/after the GT span (blocks larger than the GT box)
        if j2 > j1:
            out.update(own[j1:j2])
        elif own:
            out.add(own[min(max(j1 - 1, 0), len(own) - 1)])
    if not out:  # something differs but no token could be attributed: all are responsible
        out = set(range(len(reg)))
    return out


def recall_report(
    blocks: list[Block], gt: dict[str, Any], page_map: dict[int, int]
) -> tuple[float, list[tuple[str, str]], list[str]]:
    """(recall, per differing GT block (id, 'caught'/'MISS ...'), lines for the printout)."""
    differing: list[tuple[str, str]] = []
    lines: list[str] = []
    for g in gt["blocks"]:
        reg = region(blocks, g, page_map[g["page"]])
        gt_tokens = tokens(g["text"])
        if contains(tokens(" ".join(b.raw_text for b in reg)), gt_tokens):
            continue
        if not reg:
            differing.append((g["id"], "MISS: no text block covers it (dropped)"))
        else:
            owners = differing_owners(reg, gt_tokens)
            high = [reg[i] for i in sorted(owners) if (reg[i].confidence or 0.0) >= THRESHOLD]
            differing.append(
                (
                    g["id"],
                    "caught"
                    if not high
                    else "MISS: " + ", ".join(f"{b.id} conf {b.confidence}" for b in high),
                )
            )
        lines.append(
            f"  {g['id']}: {differing[-1][1]}; region "
            + str([(b.id, b.confidence, b.raw_text[:40]) for b in reg])
        )
    caught = sum(1 for _, s in differing if s == "caught")
    recall = caught / len(differing) if differing else 1.0
    return recall, differing, lines


@pytest.mark.skipif(
    not (PDF.is_file() and GT.is_file()) or os.environ.get("MANUALLABOR_LIVE") != "1",
    reason="live-only: needs tests/fixtures/real/real-manual.pdf and MANUALLABOR_LIVE=1",
)
def test_real_manual_recall(requires_docling: None, tmp_path: Path) -> None:
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
    blocks = load_scored_blocks(paths, paths.list_slugs()[0])

    recall, differing, lines = recall_report(blocks, gt, page_map)
    caught = sum(1 for _, s in differing if s == "caught")
    print(
        f"\nreal manual (7 GT pages, {len(gt['blocks'])} GT blocks): {len(differing)} differ "
        f"from GT, {caught} caught below {THRESHOLD} -> recall {recall:.3f}\n" + "\n".join(lines)
    )
    assert len(differing) >= 10  # non-vacuous
    assert recall >= 0.95, [d for d in differing if d[1] != "caught"]
