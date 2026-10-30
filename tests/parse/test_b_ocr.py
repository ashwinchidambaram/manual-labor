"""Tests 13-17: OCR engines, word mapping, role resolution and attachment."""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from manuallabor import ids
from manuallabor.contracts import ProjectConfig
from manuallabor.contracts.block import Block, OcrWord
from manuallabor.contracts.enums import BlockType, OcrEngine
from manuallabor.contracts.io import read_json
from manuallabor.parse import ocr as ocr_mod
from manuallabor.parse.ocr import (
    RapidOcrAdapter,
    TesseractAdapter,
    build_engines,
    engine_versions,
    map_rapid_words,
    ocr_page_to_parse,
    px_to_pt,
    rapid_to_page,
    resolve_engine,
)
from manuallabor.parse.ocr_attach import attach_ocr
from manuallabor.parse.types import Line, OcrOutput, OcrPage
from tests.parse.conftest import Parsed

FIX = Path(__file__).resolve().parents[1] / "fixtures"
TOK = re.compile(r"[^\s|•]+")
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract")


def _f1(a: str, b: str) -> float:
    ta, tb = TOK.findall(a), TOK.findall(b)
    pool = list(tb)
    hit = 0
    for t in ta:
        if t in pool:
            pool.remove(t)
            hit += 1
    if hit == 0:
        return 0.0
    p, r = hit / len(ta), hit / len(tb)
    return 2 * p * r / (p + r)


def _render(pdf: str, page_no: int, out: Path, dpi: int = 300) -> tuple[Path, tuple[float, float]]:
    doc = pymupdf.open(str(FIX / pdf))
    page = doc[page_no - 1]
    path = out / f"{Path(pdf).stem}-p{page_no:03d}.png"
    page.get_pixmap(dpi=dpi).save(str(path))
    return path, (page.rect.width, page.rect.height)


def _gt(name: str) -> dict[str, Any]:
    return json.loads((FIX / "ground_truth" / f"{name}.json").read_text())


def _page_text(op: OcrPage) -> str:
    return "\n".join(ln.text for ln in op.lines)


# ---------------------------------------------------------------- test 13


@pytest.fixture(scope="module")
def scanned_p2(tmp_path_factory: pytest.TempPathFactory) -> dict[str, OcrPage]:
    out = tmp_path_factory.mktemp("scanned")
    png, size = _render("scanned.pdf", 2, out)
    pages: dict[str, OcrPage] = {}
    adapters: list[Any] = [RapidOcrAdapter()]
    if shutil.which("tesseract"):
        adapters.append(TesseractAdapter())
    for a in adapters:
        pages[a.engine.value] = a.ocr_page(png, 2, size, 300)
    return pages


def test_13_scanned_word_confidences_and_f1(scanned_p2: dict[str, OcrPage]) -> None:
    gt = _gt("scanned")
    want = "\n".join(
        "\n".join(b["raw_lines"]) for b in gt["blocks"] if b["page"] == 2 and b["type"] != "figure"
    )
    floors = {"tesseract": 0.95, "rapidocr": 0.85}
    for engine, op in scanned_p2.items():
        assert op.lines and op.dpi == 300 and op.engine.value == engine
        for ln in op.lines:
            assert ln.words, ln
            for w in ln.words:
                assert 0.0 <= w.confidence <= 1.0
                assert w.bbox is not None
                x0, y0, x1, y1 = w.bbox
                assert 0 <= x0 <= x1 <= op.width and 0 <= y0 <= y1 <= op.height
            assert ln.text == " ".join(w.text for w in ln.words) or engine == "rapidocr"
        score = _f1(_page_text(op), want)
        print(f"OCR F1 scanned p2 {engine}: {score:.4f}")
        assert score >= floors[engine], (engine, score)


def test_13_blocks_carry_words(scanned_p2: dict[str, OcrPage]) -> None:
    for engine, op in scanned_p2.items():
        pp = ocr_page_to_parse(op, "ocr" if engine == "tesseract" else "ocr_alt")
        assert not pp.has_text_layer and pp.blocks
        assert [b.order for b in pp.blocks] == list(range(len(pp.blocks)))
        for b in pp.blocks:
            assert b.bbox is not None and b.lines
            assert all(ln.words for ln in b.lines)
            assert b.text == "\n".join(ln.text for ln in b.lines)
        covered = sum(len(b.lines) for b in pp.blocks)
        assert covered == len(op.lines)  # nothing dropped


def test_13_parsed_scanned_blocks_carry_ocr_words(parsed: Parsed) -> None:
    """Pipeline blocks (not raw OCR): every non-figure block has words with confidences in [0,1]."""
    blocks = parsed.blocks("scanned")
    assert blocks
    for b in blocks:
        assert b.ocr_words is not None, b.id
        if b.type == BlockType.figure:
            continue
        assert b.ocr_words, f"{b.id} ({b.type.value}) has no OCR words"
        assert "ocr" in b.raw_text_by_parser or "ocr_alt" in b.raw_text_by_parser, b.id
        for w in b.ocr_words:
            assert 0.0 <= w.confidence <= 1.0


# ---------------------------------------------------------------- test 14 / attach


def _gt_blocks(name: str, slug: str) -> list[Block]:
    gt = _gt(name)
    per_page: dict[int, int] = {}
    figs: dict[int, int] = {}
    out: list[Block] = []
    for i, b in enumerate(gt["blocks"]):
        page = b["page"]
        per_page[page] = per_page.get(page, 0) + 1
        fid = None
        if b["type"] == "figure":
            figs[page] = figs.get(page, 0) + 1
            fid = ids.figure_id(slug, page, figs[page])
        out.append(
            Block(
                id=ids.block_id(slug, page, per_page[page]),
                doc_id=slug,
                page=page,
                bbox=b["bbox"],
                type=BlockType(b["type"]),
                reading_order=i,
                raw_text=b["text"],
                raw_source="pymupdf",
                raw_text_by_parser={"pymupdf": b["text"]},
                figure_id=fid,
            )
        )
    return out


@pytest.fixture(scope="module")
def clean_ocr(tmp_path_factory: pytest.TempPathFactory) -> OcrOutput:
    out = tmp_path_factory.mktemp("clean")
    doc = pymupdf.open(str(FIX / "clean.pdf"))
    n = len(doc)
    renders = [_render("clean.pdf", p, out) for p in range(1, n + 1)]
    adapter = TesseractAdapter() if shutil.which("tesseract") else RapidOcrAdapter()

    def run(i: int) -> OcrPage:
        png, size = renders[i]
        return adapter.ocr_page(png, i + 1, size, 300)

    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(run, range(n)))
    return OcrOutput(
        role="ocr",
        engine=adapter.engine,
        version=adapter.version(),
        source_sha256="0" * 64,
        pages=pages,
    )


def test_14_attach_on_born_digital(clean_ocr: OcrOutput) -> None:
    blocks = _gt_blocks("clean", "clean")
    n_pages = len(clean_ocr.pages)
    out = attach_ocr(blocks, clean_ocr, [True] * n_pages)
    assert [b.id for b in out] == [b.id for b in blocks]
    scores = []
    pymu_all, ocr_all = [], []
    for b in out:
        assert b.ocr_words is not None and "ocr" in b.raw_text_by_parser
        assert b.raw_text_by_parser["pymupdf"] == b.raw_text  # untouched
        for w in b.ocr_words:
            assert 0.0 <= w.confidence <= 1.0
        if b.type == BlockType.figure:
            continue
        assert b.ocr_words, f"{b.id} ({b.type.value}) has no OCR words"
        assert b.raw_text_by_parser["ocr"].split() == [w.text for w in b.ocr_words]
        pymu_all.append(b.raw_text_by_parser["pymupdf"])
        ocr_all.append(b.raw_text_by_parser["ocr"])
        scores.append(_f1(b.raw_text_by_parser["pymupdf"], b.raw_text_by_parser["ocr"]))
    doc_f1 = _f1("\n".join(pymu_all), "\n".join(ocr_all))
    engine = clean_ocr.engine.value
    print(f"token F1 pymupdf vs ocr (clean, doc, {engine}): {doc_f1:.4f}")
    floors = {"tesseract": 0.95, "rapidocr": 0.85}  # same floors as test 13
    assert doc_f1 >= floors[engine], (engine, doc_f1)


def test_14_attach_is_pure_and_deterministic(clean_ocr: OcrOutput) -> None:
    blocks = _gt_blocks("clean", "clean")
    flags = [True] * len(clean_ocr.pages)
    a = attach_ocr(blocks, clean_ocr, flags)
    b = attach_ocr(list(reversed(blocks)), clean_ocr, flags)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in reversed(b)]
    assert all(x.ocr_words is None for x in blocks)  # inputs not mutated


def _blk(slug: str, page: int, n: int, bbox: list[float], order: int) -> Block:
    return Block(
        id=ids.block_id(slug, page, n),
        doc_id=slug,
        page=page,
        bbox=bbox,
        type=BlockType.paragraph,
        reading_order=order,
        raw_text="x",
        raw_source="pymupdf",
        raw_text_by_parser={"pymupdf": "x"},
    )


def _line(words: list[tuple[str, float, list[float]]], nid: str) -> Line:
    ws = [OcrWord(text=t, confidence=c, bbox=b) for t, c, b in words]
    x0 = min(w[2][0] for w in words)
    y0 = min(w[2][1] for w in words)
    x1 = max(w[2][2] for w in words)
    y1 = max(w[2][3] for w in words)
    return Line(
        text=" ".join(t for t, _, _ in words), bbox=[x0, y0, x1, y1], words=ws, native_id=nid
    )


def test_14_attach_rules() -> None:
    outer = _blk("d", 1, 1, [0, 0, 200, 200], 0)
    inner = _blk("d", 1, 2, [10, 10, 100, 40], 1)
    scanned = _blk("d", 2, 1, [0, 0, 200, 200], 2)
    lines = [
        _line([("beta", 0.9, [50, 20, 70, 30]), ("alpha", 0.8, [20, 20, 45, 30])], "a"),
        _line([("gamma", 0.7, [20, 120, 60, 130])], "b"),
        _line(
            [("edge", 0.6, [101, 20, 110, 30])], "c"
        ),  # center 105.5 is outside inner even with the 2 pt pad
        _line([("lost", 0.5, [300, 300, 320, 310])], "d"),
    ]
    ocr = OcrOutput(
        role="ocr",
        engine=OcrEngine.tesseract,
        version="t",
        source_sha256="1" * 64,
        pages=[
            OcrPage(
                page=1, engine=OcrEngine.tesseract, dpi=300, width=612, height=792, lines=lines
            ),
            OcrPage(
                page=2, engine=OcrEngine.tesseract, dpi=300, width=612, height=792, lines=lines
            ),
        ],
    )
    out = attach_ocr([outer, inner, scanned], ocr, [True, False])
    by_id = {b.id: b for b in out}
    i, o, s = by_id[inner.id], by_id[outer.id], by_id[scanned.id]
    assert i.ocr_words is not None and [w.text for w in i.ocr_words] == ["alpha", "beta"]
    assert i.raw_text_by_parser["ocr"] == "alpha beta"  # words ordered by x within the line
    assert o.ocr_words is not None
    assert [w.text for w in o.ocr_words] == ["edge", "gamma"]  # ordered by line y0
    assert "lost" not in o.raw_text_by_parser["ocr"]
    assert s.ocr_words is None and "ocr" not in s.raw_text_by_parser  # scanned page untouched


# ---------------------------------------------------------------- test 15


@needs_tesseract
def test_15_pixel_to_point_conversion(tmp_path: Path) -> None:
    assert px_to_pt(2550, 300) == pytest.approx(612.0, abs=1e-9)
    assert px_to_pt(3300, 300) == pytest.approx(792.0, abs=1e-9)
    png, size = _render("clean.pdf", 3, tmp_path)
    op = TesseractAdapter().ocr_page(png, 3, size, 300)
    doc = pymupdf.open(str(FIX / "clean.pdf"))
    ref = doc[2].get_text("words")
    matched = good = 0
    for ln in op.lines:
        for w in ln.words:
            assert w.bbox is not None
            cands = [r for r in ref if r[4] == w.text]
            if not cands:
                continue
            cx, cy = (w.bbox[0] + w.bbox[2]) / 2, (w.bbox[1] + w.bbox[3]) / 2
            r = min(
                cands,
                key=lambda r: abs((r[0] + r[2]) / 2 - cx) + abs((r[1] + r[3]) / 2 - cy),
            )
            matched += 1
            # glyph boxes are tighter than font boxes vertically, so compare x edges and centers
            ok = (
                abs(w.bbox[0] - r[0]) <= 3
                and abs(w.bbox[2] - r[2]) <= 3
                and abs(cy - (r[1] + r[3]) / 2) <= 3
            )
            good += ok
    assert matched >= 500
    assert good / matched >= 0.95


# ---------------------------------------------------------------- test 16


def test_16_rapid_word_mapping() -> None:
    frags = [
        ("Tor", 0.99, [10.0, 5.0, 30.0, 15.0]),
        ("que", 0.80, [30.0, 5.0, 50.0, 15.0]),
        ("35", 0.95, [60.0, 5.0, 75.0, 15.0]),
        ("N·m", 0.90, [80.0, 6.0, 105.0, 14.0]),
    ]
    out = map_rapid_words("Torque 35 N·m", frags)
    assert [t for t, _, _ in out] == ["Torque", "35", "N·m"]
    assert out[0][1] == pytest.approx(0.80)  # min of fragments
    assert out[0][2] == [10.0, 5.0, 50.0, 15.0]  # union box
    assert out[1][1] == pytest.approx(0.95) and out[2][2] == [80.0, 6.0, 105.0, 14.0]


def test_16_fragment_spanning_tokens_and_mismatch() -> None:
    frags = [("Acme", 0.9, [0.0, 0.0, 10.0, 5.0]), ("X200Service", 0.7, [12.0, 0.0, 40.0, 5.0])]
    out = map_rapid_words("Acme X200 Service", frags)
    assert [t for t, _, _ in out] == ["Acme", "X200", "Service"]
    assert out[1][1] == out[2][1] == pytest.approx(0.7)
    assert out[1][2] == out[2][2] == [12.0, 0.0, 40.0, 5.0]
    # concatenation mismatch: the fragments themselves become the words
    bad = [("Acm", 0.9, [0.0, 0.0, 8.0, 5.0]), ("e", 0.5, [8.0, 0.0, 10.0, 5.0])]
    assert map_rapid_words("Acme X", bad) == [
        ("Acm", 0.9, [0.0, 0.0, 8.0, 5.0]),
        ("e", 0.5, [8.0, 0.0, 10.0, 5.0]),
    ]


def test_16_rapid_page_conversion_scales_pixels() -> None:
    quad = [[300, 150], [900, 150], [900, 210], [300, 210]]
    wr = [
        (
            ("Hello", 0.9, [[300, 150], [550, 150], [550, 210], [300, 210]]),
            ("world", 0.7, [[600, 150], [900, 150], [900, 210], [600, 210]]),
        )
    ]
    page = rapid_to_page(["Hello world"], [0.8], [quad], wr, 1, (612.0, 792.0), 300)
    (ln,) = page.lines
    assert ln.text == "Hello world" and ln.native_id == "r0"
    assert ln.words[0].bbox == [72.0, 36.0, 132.0, 50.4]
    assert [w.confidence for w in ln.words] == [0.9, 0.7]
    assert ln.bbox == [72.0, 36.0, 216.0, 50.4]


# ---------------------------------------------------------------- test 17


def test_17_resolve_and_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_mod.shutil, "which", lambda name: "/usr/bin/tesseract")
    assert resolve_engine("auto") == "tesseract"
    assert resolve_engine(OcrEngine.auto) == "tesseract"
    assert resolve_engine("rapidocr") == "rapidocr"
    cfg = ProjectConfig(name="t", ocr_engine=OcrEngine.rapidocr)
    ocr, alt = build_engines(cfg)
    assert (ocr.engine, alt.engine if alt else None) == (OcrEngine.rapidocr, OcrEngine.tesseract)

    monkeypatch.setattr(ocr_mod.shutil, "which", lambda name: None)
    warnings: list[str] = []
    for configured in (OcrEngine.auto, OcrEngine.tesseract, OcrEngine.rapidocr):
        assert resolve_engine(configured) == "rapidocr"
        warnings.clear()
        ocr, alt = build_engines(
            ProjectConfig(name="t", ocr_engine=configured), warn=warnings.append
        )
        assert ocr.engine == OcrEngine.rapidocr and alt is None
        assert len(warnings) == 1 and "tesseract" in warnings[0]
        versions = engine_versions(ocr, alt)
        assert versions["ocr_alt"] == "unavailable"
        assert versions["ocr"].startswith("rapidocr:rapidocr==")


def test_17_default_warning_is_a_json_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ocr_mod.shutil, "which", lambda name: None)
    build_engines(ProjectConfig(name="t"))
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["status"] == "warning" and rec["stage"] == "ocr"


@needs_tesseract
def test_17_both_engines_agree_on_structure(scanned_p2: dict[str, OcrPage]) -> None:
    t, r = scanned_p2["tesseract"], scanned_p2["rapidocr"]
    assert (t.width, t.height, t.dpi) == (r.width, r.height, r.dpi)
    for op in (t, r):
        for ln in op.lines:
            for w in ln.words:
                assert isinstance(w, OcrWord) and w.bbox is not None


def test_14_pipeline_blocks_carry_ocr_agreeing_with_text_layer(parsed: Parsed) -> None:
    """OCR attached to the pipeline's own clean.pdf blocks agrees with the text layer."""
    blocks = parsed.blocks("clean")
    ocr_out = read_json(parsed.paths.doc("clean").parser_output("ocr"), OcrOutput)
    again = attach_ocr(blocks, ocr_out, [True] * len(ocr_out.pages))
    assert [b.model_dump() for b in again] == [b.model_dump() for b in blocks]  # pure/idempotent
    pymu, ocr = [], []
    for b in blocks:
        if b.type == BlockType.figure:
            assert b.ocr_words is not None
            continue
        assert b.ocr_words, f"{b.id} ({b.type.value}) has no OCR words"
        assert b.raw_text_by_parser["ocr"].split() == [w.text for w in b.ocr_words]
        pymu.append(b.raw_text_by_parser["pymupdf"])
        ocr.append(b.raw_text_by_parser["ocr"])
    score = _f1("\n".join(pymu), "\n".join(ocr))
    print(f"word agreement pymupdf vs ocr (pipeline clean blocks): {score:.4f}")
    assert score >= 0.98
