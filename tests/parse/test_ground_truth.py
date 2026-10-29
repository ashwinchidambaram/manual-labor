"""Tests 4-7 and 9-12: parsed blocks against the fixture ground truth."""

from __future__ import annotations

import pymupdf
import pytest
from pydantic import TypeAdapter

from manuallabor.contracts.enums import BlockType
from manuallabor.parse.geometry import expand, iou
from manuallabor.parse.types import FigureCandidate
from tests.parse.conftest import FIXTURES, Parsed
from tests.parse.gt import BORN_DIGITAL, f1, f1_counts, gt_text, load_gt, match_blocks, tokens

HF_TYPES = {"header", "footer"}


def _non_hf(gt: dict) -> list[int]:  # type: ignore[type-arg]
    return [i for i, b in enumerate(gt["blocks"]) if not b["is_header_footer"]]


@pytest.mark.parametrize("stem", BORN_DIGITAL)
def test_04_headers_and_footers_exact(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    blocks = parsed.blocks(stem)
    want = {(b["page"], b["type"]) for b in gt["blocks"] if b["is_header_footer"]}
    got = {(b.page, b.type.value) for b in blocks if b.type.value in HF_TYPES}
    assert got == want
    doc = parsed.doc(stem)
    assert doc.stripped_headers == [gt["header_text"]] == ["Acme X200 Service Manual"]
    footer_pages = sorted(p for p, t in want if t == "footer")
    assert doc.stripped_footers == sorted(f"Page {n}" for n in footer_pages)


def test_05_scanned_header_detection(parsed: Parsed) -> None:
    gt = load_gt("scanned")
    want = {b["page"] for b in gt["blocks"] if b["type"] == "header"}
    got = {b.page for b in parsed.blocks("scanned") if b.type == BlockType.header}
    print(f"scanned header pages detected: {len(got & want)}/{len(want)}")
    assert len(got & want) >= 9


@pytest.mark.parametrize("stem", BORN_DIGITAL)
def test_06_blocks_match_and_text_f1(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    gb = gt["blocks"]
    matched = match_blocks(gb, parsed.blocks(stem))
    idx = _non_hf(gt)
    ratio = sum(1 for i in idx if i in matched) / len(idx)
    tp = n_pred = n_ref = 0
    for i in idx:
        if i in matched:
            a, b, c = f1_counts(tokens(matched[i].raw_text), tokens(gt_text(gb[i])))
            tp, n_pred, n_ref = tp + a, n_pred + b, n_ref + c
    score = f1(tp, n_pred, n_ref)
    print(f"{stem}: matched ratio {ratio:.4f}, token F1 {score:.4f}")
    assert ratio >= 0.98
    assert score >= 0.98


@pytest.mark.parametrize("stem", ["clean", "twocol", "tables", "figures", "scanned"])
def test_07_no_silent_drops(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    blocks = parsed.blocks(stem)
    floor = 0.85 if stem == "scanned" else 0.98
    for g in gt["blocks"]:
        ref = tokens(gt_text(g))
        if not ref:
            continue
        box = expand(g["bbox"], 8.0) if stem == "scanned" else g["bbox"]
        pool: list[str] = []
        for b in blocks:
            if b.page == g["page"] and b.bbox is not None and iou(box, b.bbox) > 0:
                pool.extend(tokens(b.raw_text))
                if stem == "scanned":  # an OCR substitution in one reading is not a drop
                    for text in b.raw_text_by_parser.values():
                        pool.extend(tokens(text))
        tp, _, n_ref = f1_counts(pool, ref)
        assert tp / n_ref >= floor, (stem, g["page"], g["text"][:40], tp / n_ref)


@pytest.mark.parametrize("stem", BORN_DIGITAL)
def test_09_types_and_heading_fields(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    gb = gt["blocks"]
    matched = match_blocks(gb, parsed.blocks(stem))
    ok = 0
    for i, b in matched.items():
        want = gb[i]["type"]
        if want in {"figure", "table", "header", "footer"}:
            assert b.type.value == want, (stem, gb[i]["page"], gb[i]["text"][:30])
        if b.type.value == want:
            ok += 1
        if want == "heading" and b.type.value == "heading":
            assert (b.heading_level, b.section_number) == (
                gb[i]["heading_level"],
                gb[i]["section_number"],
            ), (stem, gb[i]["text"])
    assert ok / len(matched) >= 0.95


@pytest.mark.parametrize("stem", ["twocol", "clean"])
def test_10_reading_order(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    matched = match_blocks(gt["blocks"], parsed.blocks(stem))
    by_page: dict[int, list[tuple[int, int]]] = {}
    for gi, b in matched.items():
        by_page.setdefault(b.page, []).append((b.reading_order, gi))
    for page, items in by_page.items():
        gts = [gi for _, gi in sorted(items)]
        assert gts == sorted(gts) and len(set(gts)) == len(gts), (stem, page)


@pytest.mark.parametrize("stem", ["figures", "clean", "twocol"])
def test_11_figures(parsed: Parsed, stem: str) -> None:
    gt = load_gt(stem)
    blocks = parsed.blocks(stem)
    assert {b.figure_id for b in blocks if b.type == BlockType.figure} == {
        f["expected_id"] for f in gt["figures"]
    }
    cands = TypeAdapter(list[FigureCandidate]).validate_json(
        parsed.paths.doc(stem).figures.read_text()
    )
    by_id = {c.figure_id: c for c in cands}
    pdf = pymupdf.open(FIXTURES / f"{stem}.pdf")
    for f in gt["figures"]:
        c = by_id[f["expected_id"]]
        kind = f["expected_extraction"]
        if kind == "native":
            assert c.image_xrefs, f["expected_id"]
            sizes = {
                (pdf.extract_image(x)["width"], pdf.extract_image(x)["height"])
                for x in c.image_xrefs
            }
            assert (f["source_image"]["width"], f["source_image"]["height"]) in sizes
        elif kind == "vector":
            assert c.has_drawings, f["expected_id"]
        else:  # crop / composite: raster plus drawing
            assert c.image_xrefs and c.has_drawings, f["expected_id"]


def test_12_scanned_figures_from_docling(parsed: Parsed) -> None:
    gt = load_gt("scanned")
    blocks = parsed.blocks("scanned")
    figs = [b for b in blocks if b.type == BlockType.figure]
    for f in gt["figures"]:
        hits = [
            b
            for b in figs
            if b.page == f["page"] and b.bbox is not None and iou(b.bbox, f["bbox"]) >= 0.3
        ]
        assert hits, f["expected_id"]
        assert any(b.raw_source == "docling" for b in hits)
    w, h = gt["page_size"]
    for b in figs:
        assert b.bbox is not None
        area = (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])
        assert area < 0.8 * w * h


SCANNED_MATCH_FLOOR = 0.90  # was 0.50 before the OCR heading/paragraph grouping fix (now 0.9375)


def test_13b_scanned_headings_and_bbox_match(parsed: Parsed) -> None:
    """Scanned section headings stay separate heading blocks; GT bbox matching improves."""
    gt = load_gt("scanned")
    gb = gt["blocks"]
    blocks = parsed.blocks("scanned")
    heads = [b for b in gb if b["type"] == "heading"]
    assert len(heads) == 18
    hit = 0
    for g in heads:
        cands = [
            b
            for b in blocks
            if b.page == g["page"] and b.bbox is not None and b.type.value == "heading"
        ]
        best = max(cands, key=lambda b: iou(g["bbox"], b.bbox or [0, 0, 0, 0]), default=None)
        if best is None or best.bbox is None or iou(g["bbox"], best.bbox) < 0.3:
            continue
        tp, n_pred, n_ref = f1_counts(tokens(best.raw_text), tokens(gt_text(g)))
        hit += f1(tp, n_pred, n_ref) >= 0.8
    matched = match_blocks(gb, blocks)
    idx = _non_hf(gt)
    ratio = sum(1 for i in idx if i in matched) / len(idx)
    print(f"scanned: headings {hit}/18, bbox-matched ratio {ratio:.4f}")
    assert hit >= 16
    assert ratio >= SCANNED_MATCH_FLOOR


def test_scanned_gt_lists_have_parsed_list_blocks(parsed: Parsed) -> None:
    gt = load_gt("scanned")
    gt_lists = [b for b in gt["blocks"] if b["type"] == "list"]
    got = [b for b in parsed.blocks("scanned") if b.type == BlockType.list and b.bbox]
    print(f"scanned lists: parsed {len(got)} vs GT {len(gt_lists)}")
    assert abs(len(got) - len(gt_lists)) <= 1
    for g in gt_lists:
        best = max((iou(g["bbox"], b.bbox) for b in got if b.page == g["page"]), default=0.0)
        assert best >= 0.3, (g["page"], g["raw_lines"][:2], best)


def test_scanned_captions_are_their_own_blocks(parsed: Parsed) -> None:
    gt = load_gt("scanned")
    gt_caps = [b for b in gt["blocks"] if b["type"] == "caption"]
    got = [b for b in parsed.blocks("scanned") if b.type == BlockType.caption and b.bbox]
    assert gt_caps
    for g in gt_caps:
        cands = [b for b in got if b.page == g["page"] and iou(g["bbox"], b.bbox) >= 0.3]
        assert cands, (g["page"], g["raw_lines"])
        b = max(cands, key=lambda b: iou(g["bbox"], b.bbox))
        ref, pred = tokens(gt_text(g)), tokens(b.raw_text)
        assert f1(*f1_counts(pred, ref)) >= 0.8, (g["raw_lines"], b.raw_text)
        assert len(pred) <= 2 * len(ref), (g["raw_lines"], b.raw_text)
