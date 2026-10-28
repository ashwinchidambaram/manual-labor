"""F1-F11: fixture presence, determinism and content gates (design 00-contracts section 9)."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import imagehash
import pymupdf
import pytest
from PIL import Image

from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import BlockType, Extraction
from manuallabor.ids import FIGURE_ID_RE, doc_slug_from_filename
from tests.fixtures.gen.ground_truth import GroundTruth
from tests.fixtures.gen.make_fixtures import FIXTURE_FILES, STEMS, generate

FIX = Path(__file__).resolve().parents[1] / "fixtures"
PDF_STEMS = ["clean", "twocol", "tables", "figures", "scanned"]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def sums() -> dict[str, str]:
    return json.loads((FIX / "CHECKSUMS.json").read_text())


@pytest.fixture(scope="module")
def gt() -> dict[str, GroundTruth]:
    return {
        s: GroundTruth.model_validate_json((FIX / "ground_truth" / f"{s}.json").read_text())
        for s in STEMS
    }


def _tokens(lines: list[str]) -> list[str]:
    return [t for line in lines for t in line.split()]


def test_f1_files_exist_and_match_checksums(sums, gt):
    expected = (
        FIXTURE_FILES
        + [f"ground_truth/{s}.json" for s in STEMS]
        + ["project-a/project.json", "project-a/sources/clean.pdf", "project-a/sources/figures.pdf"]
    )
    assert sorted(sums) == sorted(expected)
    for rel, digest in sums.items():
        assert _sha(FIX / rel) == digest, rel
    for stem, g in gt.items():
        assert g.sha256 == sums[g.file]
        assert g.file in FIXTURE_FILES and g.file.startswith(stem)


def test_f2_regeneration_is_byte_identical(sums, tmp_path):
    again = generate(tmp_path)
    assert again == sums
    for rel, digest in sums.items():
        assert _sha(tmp_path / rel) == digest, rel


def test_f3_ground_truth_consistency(gt):
    for stem, g in gt.items():
        assert g.expected_slug == doc_slug_from_filename(g.file)
        assert [b.index for b in g.blocks] == list(range(len(g.blocks)))
        ids = [f.expected_id for f in g.figures]
        assert len(ids) == len(set(ids)), stem
        for f in g.figures:
            m = FIGURE_ID_RE.match(f.expected_id)
            assert m and m.group("slug") == g.expected_slug
            assert int(m.group("page")) == f.page
            for bi in f.referenced_by:
                assert f"Figure {f.number}" in g.blocks[bi].text, (stem, f.expected_id)
            if f.caption_block_index is not None:
                cb = g.blocks[f.caption_block_index]
                assert cb.type == BlockType.caption and cb.page == f.page
                assert cb.text == f.caption
            if f.duplicate_of:
                assert f.duplicate_of in ids
                assert (
                    next(x for x in g.figures if x.expected_id == f.duplicate_of).duplicate_of
                    is None
                )


@pytest.mark.parametrize("stem", ["clean", "twocol", "tables", "figures"])
def test_f4_text_layer_recall(stem, gt):
    doc = pymupdf.open(FIX / f"{stem}.pdf")
    want = got = 0
    worst = 1.0
    for b in gt[stem].blocks:
        if b.type == BlockType.figure or b.bbox is None:
            continue
        rect = pymupdf.Rect(*b.bbox) + (-3, -3, 3, 3)
        have = set(doc[b.page - 1].get_text("text", clip=rect).split())
        toks = _tokens(b.raw_lines)
        hit = sum(t in have for t in toks)
        want += len(toks)
        got += hit
        worst = min(worst, hit / max(len(toks), 1))
    assert got / want >= 0.98
    assert worst >= 0.9


def _image_rects(doc, page_no):
    out = []
    for img in doc[page_no - 1].get_images(full=True):
        xref = img[0]
        for r in doc[page_no - 1].get_image_rects(xref):
            out.append((xref, r, img[2], img[3]))
    return out


def test_f5_figures_pdf(gt):
    g = gt["figures"]
    doc = pymupdf.open(FIX / "figures.pdf")
    assert len(g.figures) >= 12
    good = sum(f.expected_extraction in (Extraction.native, Extraction.vector) for f in g.figures)
    assert good / len(g.figures) >= 0.95
    raster = [f for f in g.figures if f.source_image]
    assert len(raster) == 8
    by_id = {}
    for f in raster:
        match = None
        for xref, r, w, h in _image_rects(doc, f.page):
            if all(abs(a - b) <= 1 for a, b in zip([r.x0, r.y0, r.x1, r.y1], f.bbox, strict=True)):
                match = (xref, w, h)
        assert match, f.expected_id
        assert (match[1], match[2]) == (f.source_image.width, f.source_image.height)
        by_id[f.expected_id] = match[0]
    dups = [f for f in raster if f.duplicate_of and not f.near_duplicate]
    near = [f for f in raster if f.near_duplicate]
    assert len(dups) == 1 and len(near) == 1

    def img_bytes(xref):
        return doc.extract_image(xref)["image"]

    orig = dups[0].duplicate_of
    # the in-document duplicate is a separate PDF image object (own xref), same pixels
    assert by_id[dups[0].expected_id] != by_id[orig]
    assert (
        hashlib.sha256(img_bytes(by_id[dups[0].expected_id])).digest()
        == hashlib.sha256(img_bytes(by_id[orig])).digest()
    )
    assert dups[0].source_image == next(f for f in raster if f.expected_id == orig).source_image
    assert near[0].duplicate_of == orig

    def ph(xref):
        return imagehash.phash(Image.open(io.BytesIO(img_bytes(xref))))

    assert ph(by_id[near[0].expected_id]) - ph(by_id[orig]) <= 4
    # one figure without a caption, one with a caption and no reference
    assert sum(f.caption is None for f in g.figures) == 1
    assert sum(f.caption is not None and not f.referenced_by for f in g.figures) == 1
    assert (
        sum(1 for f in g.figures if any(g.blocks[i].page != f.page for i in f.referenced_by)) == 2
    )


def test_f6_scanned(gt):
    sc = pymupdf.open(FIX / "scanned.pdf")
    cl = pymupdf.open(FIX / "clean.pdf")
    assert sc.page_count == cl.page_count == gt["scanned"].page_count
    for page in sc:
        assert page.get_text().strip() == ""
        imgs = page.get_images(full=True)
        assert len(imgs) == 1
        assert abs(imgs[0][2] / 8.5 - 300) <= 2
    assert (FIX / "scanned.pdf").stat().st_size < 15 * 1024 * 1024
    assert gt["scanned"].text_is_reference and gt["scanned"].derived_from == "clean"


def test_f7_clean(gt):
    g = gt["clean"]
    doc = pymupdf.open(FIX / "clean.pdf")
    assert doc.page_count == 12
    for n in range(2, 13):
        text = doc[n - 1].get_text()
        assert "Acme X200 Service Manual" in text and f"Page {n}" in text
    assert "Page 1" not in doc[0].get_text()
    assert sum(b.hyphenated for b in g.blocks) >= 3
    specs = {s for b in g.blocks for s in b.numeric_specs}
    assert {"35 N·m", "M8", "12 V", "P/N 4471-A"} <= specs
    assert sum(b.type == BlockType.list for b in g.blocks) >= 4
    assert len(g.figures) == 3 and all(f.caption and f.referenced_by for f in g.figures)
    pages = {f.number: f.page for f in g.figures}
    assert pages[1] == pages[2] and pages[3] == pages[1] - 1
    for b in g.blocks:
        if b.hyphenated:
            assert any(line.endswith("-") for line in b.raw_lines)


def test_f8_tables(gt):
    tabs = [b.table for b in gt["tables"].blocks if b.table]
    assert len(tabs) >= 5
    for t in tabs:
        assert any(c.row == 0 and c.is_header for c in t.cells)
    assert any(c.row_span > 1 or c.col_span > 1 for t in tabs for c in t.cells)
    assert any(t.ragged for t in tabs)
    assert any(not t.bordered for t in tabs)


def test_f9_twocol(gt):
    g = gt["twocol"]
    body = [b for b in g.blocks if not b.is_header_footer]
    assert {b.column for b in body} == {0, 1}
    x = {c: [b.bbox for b in body if b.column == c] for c in (0, 1)}
    assert max(bb[2] for bb in x[0]) < min(bb[0] for bb in x[1])
    for page in range(1, g.page_count + 1):
        cols = [b.column for b in body if b.page == page]
        assert cols == sorted(cols)
    comp = [f for f in g.figures if f.expected_extraction == Extraction.crop]
    assert len(comp) == 1


def test_f10_docx(gt):
    import docx

    d = docx.Document(str(FIX / "manual.docx"))
    assert len(d.inline_shapes) >= 2
    assert len(d.tables) == 1
    assert any(p.style.name.startswith("Heading") for p in d.paragraphs)
    with zipfile.ZipFile(FIX / "manual.docx") as z:
        xml = z.read("word/document.xml").decode()
    assert len(re.findall(r'<w:br w:type="page"', xml)) == 1
    g = gt["manual"]
    assert all(b.bbox is None for b in g.blocks)
    assert {b.page for b in g.blocks} == {1, 2}
    assert all(f.bbox is None for f in g.figures)


def test_f11_project_a(sums):
    cfg = ProjectConfig.model_validate_json((FIX / "project-a" / "project.json").read_text())
    for task in ("cleanup", "grouping", "vision", "embeddings", "verifier", "metadata", "agent"):
        ref = getattr(cfg.models, task)
        assert ref.provider == "mock" and ref.model == "mock-1"
    for name in ("clean.pdf", "figures.pdf"):
        assert (FIX / "project-a" / "sources" / name).read_bytes() == (FIX / name).read_bytes()


def _overlaps(r, area) -> bool:
    """Closed-interval overlap; unlike Rect.intersects it also works for zero-height lines."""
    return r.x0 <= area.x1 and r.x1 >= area.x0 and r.y0 <= area.y1 and r.y1 >= area.y0


def test_f12_vector_figures_stay_inside_their_bbox(gt):
    g = gt["figures"]
    doc = pymupdf.open(FIX / "figures.pdf")
    vec = [f for f in g.figures if f.expected_extraction == Extraction.vector]
    assert len(vec) >= 4
    tol = 0.5
    for f in vec:
        page = doc[f.page - 1]
        frame = pymupdf.Rect(*f.bbox)
        inner = pymupdf.Rect(frame.x0 - tol, frame.y0 - tol, frame.x1 + tol, frame.y1 + tol)
        cap = g.blocks[f.caption_block_index] if f.caption_block_index is not None else None
        cap_rect = pymupdf.Rect(*cap.bbox) if cap is not None else None
        touching = 0
        for d in page.get_drawings():
            r = pymupdf.Rect(d["rect"])
            if _overlaps(r, frame):
                touching += 1
                assert r.x0 >= inner.x0 and r.y0 >= inner.y0, (f.expected_id, tuple(r))
                assert r.x1 <= inner.x1 and r.y1 <= inner.y1, (f.expected_id, tuple(r))
            if cap_rect is not None:
                assert not _overlaps(r, cap_rect), (f.expected_id, tuple(r), tuple(cap_rect))
        assert touching >= 8, f.expected_id
