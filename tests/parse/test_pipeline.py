"""Tests 1-3 and 8: parse outputs, determinism, ID/ordering invariants, merge accounting."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.parse.types import MergeReport, OcrOutput, ParserOutput
from tests.parse.conftest import ALL_FIXTURES, Parsed
from tests.parse.gt import PDF_FIXTURES

ALLOWED_SKIPS = {"empty_text", "scan_background", "tiny_drawing", "table_rule", "empty_paragraph"}


def _nonskipped_pages(out: ParserOutput) -> int:
    return sum(1 for p in out.pages if p.blocks)


def test_01_parser_outputs_present(parsed: Parsed) -> None:
    for stem in ALL_FIXTURES:
        d = parsed.paths.doc(stem)
        n = parsed.doc(stem).page_count
        if stem == "manual":
            names = ["docx", "docling"]
        elif stem == "scanned":
            names = ["ocr", "ocr_alt", "docling"]
        else:
            names = ["pymupdf", "docling"]
        for name in names:
            f = d.parser_output(name)
            assert f.is_file(), (stem, name)
            if name in ("ocr", "ocr_alt"):
                oo = read_json(f, OcrOutput)
                assert sum(1 for p in oo.pages if p.lines) >= 0.8 * n, (stem, name)
            else:
                po = read_json(f, ParserOutput)
                if stem == "scanned":
                    figs = [
                        b
                        for p in po.pages
                        for b in p.blocks
                        if b.kind.value == "figure" and b.layout_only
                    ]
                    assert len(figs) >= 3
                else:
                    assert _nonskipped_pages(po) >= 0.8 * n, (stem, name)


def _hash_files(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for stem_dir in sorted((root / "docs").iterdir()):
        files = [stem_dir / "blocks.json", stem_dir / "document.json"]
        files += sorted((stem_dir / "parse").glob("*.json"))
        for f in files:
            out[str(f.relative_to(root))] = f.read_bytes()
    return out


def test_02_reparse_in_fresh_process_is_byte_identical(
    parsed: Parsed, copy_template: Callable[[], Path]
) -> None:
    dst = copy_template()
    env = dict(os.environ, PYTHONHASHSEED="123")
    proc = subprocess.run(
        [sys.executable, "-c", "from manuallabor.cli import app; app()", "parse", str(dst)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    first = _hash_files(parsed.paths.root)
    second = _hash_files(dst.resolve())
    assert first.keys() == second.keys()
    for k in first:
        assert first[k] == second[k], k


@pytest.mark.parametrize("stem", ALL_FIXTURES)
def test_03_ids_order_and_validity(parsed: Parsed, stem: str) -> None:
    doc: Document = parsed.doc(stem)
    blocks = parsed.blocks(stem)
    assert doc.block_ids == [b.id for b in blocks]
    assert [b.reading_order for b in blocks] == list(range(len(blocks)))
    pages = [b.page for b in blocks]
    assert pages == sorted(pages)
    per_page: dict[int, list[int]] = {}
    for b in blocks:
        per_page.setdefault(b.page, []).append(int(b.id.rsplit("-", 1)[1]))
    for page, ns in per_page.items():
        assert ns == list(range(1, len(ns) + 1)), (stem, page)
    # header/footer blocks are kept, and their strings are what the Document records
    hdr = sorted({b.raw_text for b in blocks if b.type.value == "header"})
    ftr = sorted({b.raw_text for b in blocks if b.type.value == "footer"})
    assert doc.stripped_headers == hdr
    assert doc.stripped_footers == ftr
    assert doc.parser_versions["parse_algo"]
    assert doc.parser_versions["ocr_engine"] in ("tesseract", "rapidocr")


@pytest.mark.parametrize("stem", PDF_FIXTURES)
def test_08_every_candidate_accounted_for(parsed: Parsed, stem: str) -> None:
    d = parsed.paths.doc(stem)
    report = read_json(d.merge, MergeReport)
    keys = [(x.parser, x.page, x.order) for x in report.dispositions]
    assert len(keys) == len(set(keys))
    ids = {b.id for b in read_json_list(d.blocks, Block)}
    for x in report.dispositions:
        if x.outcome == "skipped":
            assert x.block_id is None
            assert x.detail in ALLOWED_SKIPS
        else:
            assert x.block_id in ids
    seen = set(keys)
    for name in ("pymupdf", "docling"):
        po = read_json(d.parser_output(name), ParserOutput)
        for page in po.pages:
            for rb in page.blocks:
                assert (name, page.page, rb.order) in seen
            for sk in page.skipped:
                assert (name, page.page, sk.order) in seen
