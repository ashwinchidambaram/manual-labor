"""Tests 18 and 19: table conversion against ground truth, Markdown and raw-text rendering."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from manuallabor.contracts.block import TableCell, TableShape
from manuallabor.parse.tables import (
    from_docling,
    from_pymupdf,
    shape_of,
    table_markdown,
    table_raw_text,
    to_table_data,
)
from manuallabor.parse.types import TableCandidate

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _gt_tables() -> list[dict[str, Any]]:
    gt = json.loads((FIX / "ground_truth" / "tables.json").read_text())
    return [b for b in gt["blocks"] if b["table"]]


def _cells(cells: list[Any]) -> dict[tuple[int, int], tuple[int, int, str]]:
    out = {}
    for c in cells:
        d = c if isinstance(c, dict) else c.model_dump()
        out[(d["row"], d["col"])] = (d["row_span"], d["col_span"], d["text"])
    return out


def _docling_models_present() -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return any(hub.glob("models--docling-project--docling-layout-heron")) and any(
        hub.glob("models--docling-project--docling-models")
    )


@pytest.fixture(scope="module")
def pymupdf_tables() -> dict[int, TableCandidate]:
    doc = pymupdf.open(str(FIX / "tables.pdf"))
    out: dict[int, TableCandidate] = {}
    for i, page in enumerate(doc):
        found = page.find_tables(strategy="lines").tables
        assert len(found) == 1, f"page {i + 1}"
        out[i + 1] = from_pymupdf(found[0], page)
    return out


@pytest.fixture(scope="module")
def docling_tables() -> dict[int, TableCandidate]:
    if not _docling_models_present() and os.environ.get("MANUALLABOR_REQUIRE_DOCLING") != "1":
        pytest.skip("docling models not cached")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_page_images=False,
        generate_picture_images=False,
    )
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = conv.convert(str(FIX / "tables.pdf")).document
    out: dict[int, TableCandidate] = {}
    for item, _ in doc.iterate_items():
        if str(getattr(item.label, "value", item.label)) == "table":
            out[item.prov[0].page_no] = from_docling(item)
    return out


def test_18_pymupdf_tables_match_ground_truth(pymupdf_tables: dict[int, TableCandidate]) -> None:
    gt = _gt_tables()
    assert len(gt) == 6 and sorted(pymupdf_tables) == [b["page"] for b in gt]
    exact = 0
    for b in gt:
        t, tc = b["table"], pymupdf_tables[b["page"]]
        assert (tc.n_rows, tc.n_cols) == (t["n_rows"], t["n_cols"])
        want, got = _cells(t["cells"]), _cells(tc.cells)
        same = sum(1 for k, v in want.items() if got.get(k) == v)
        assert same / len(want) >= 0.95, (b["page"], same, len(want))
        assert set(got) == set(want)
        exact += got == want
        assert table_raw_text(tc) == b["text"]
        td = to_table_data(tc, {"pymupdf": shape_of(tc), "docling": (tc.n_rows, tc.n_cols)})
        assert len(td.markdown.split("\n")) == td.n_rows + 1
        assert set(td.shape_by_parser) == {"pymupdf", "docling"}
    assert exact == 6


def test_18_merged_and_ragged(pymupdf_tables: dict[int, TableCandidate]) -> None:
    t4 = pymupdf_tables[4]
    assert any(c.col_span == 2 for c in t4.cells)
    assert any(c.row_span == 2 for c in t4.cells)
    assert t4.header_rows == 2
    assert all(c.is_header == (c.row < 2) for c in t4.cells)
    t5 = pymupdf_tables[5]
    assert any(c.text == "" for c in t5.cells)
    assert any(c.row_span > 1 for c in t5.cells)
    assert t5.header_rows == 1
    assert pymupdf_tables[6].header_rows == 1  # borderless table


def test_18_docling_tables_match_ground_truth(docling_tables: dict[int, TableCandidate]) -> None:
    gt = _gt_tables()
    assert sorted(docling_tables) == [b["page"] for b in gt]
    for b in gt:
        t, tc = b["table"], docling_tables[b["page"]]
        assert (tc.n_rows, tc.n_cols) == (t["n_rows"], t["n_cols"])
        want, got = _cells(t["cells"]), _cells(tc.cells)
        same = sum(1 for k, v in want.items() if got.get(k) == v)
        assert same / len(want) >= 0.95, (b["page"], same, len(want))
    # empty ragged cells are materialised
    assert any(c.text == "" for c in docling_tables[5].cells)
    assert any(c.row_span > 1 for c in docling_tables[5].cells)
    assert any(c.col_span == 2 for c in docling_tables[4].cells)


def test_18_shape_agreement(
    pymupdf_tables: dict[int, TableCandidate], docling_tables: dict[int, TableCandidate]
) -> None:
    for page, tc in pymupdf_tables.items():
        td = to_table_data(tc, {"pymupdf": shape_of(tc), "docling": shape_of(docling_tables[page])})
        assert td.shape_by_parser["pymupdf"] == td.shape_by_parser["docling"]


# ---------------------------------------------------------------- test 19 (unit)


def _tc(n_rows: int, n_cols: int, cells: list[TableCell], header_rows: int = 1) -> TableCandidate:
    return TableCandidate(
        n_rows=n_rows,
        n_cols=n_cols,
        cells=sorted(cells, key=lambda c: (c.row, c.col)),
        header_rows=header_rows,
    )


def test_19_markdown_and_raw_text_with_spans() -> None:
    tc = _tc(
        3,
        3,
        [
            TableCell(row=0, col=0, row_span=2, text="Task", is_header=True),
            TableCell(row=0, col=1, col_span=2, text="Interval", is_header=True),
            TableCell(row=1, col=1, text="Hours", is_header=True),
            TableCell(row=1, col=2, text="Months", is_header=True),
            TableCell(row=2, col=0, text="Belt"),
            TableCell(row=2, col=1, text="250"),
            TableCell(row=2, col=2, text="3"),
        ],
        header_rows=2,
    )
    assert table_markdown(tc).split("\n") == [
        "| Task | Interval |  |",
        "|---|---|---|",
        "|  | Hours | Months |",
        "| Belt | 250 | 3 |",
    ]
    assert table_raw_text(tc) == "Task | Interval\nHours | Months\nBelt | 250 | 3"


def test_19_ragged_rows_and_escaping() -> None:
    tc = _tc(
        3,
        3,
        [
            TableCell(row=0, col=0, text="A|B", is_header=True),
            TableCell(row=0, col=1, text="C", is_header=True),
            TableCell(row=0, col=2, text="D", is_header=True),
            TableCell(row=1, col=0, text="x\ny"),
            TableCell(row=1, col=1, text=""),
            TableCell(row=1, col=2, text=""),
            TableCell(row=2, col=0, text="z"),
            TableCell(row=2, col=1, text="p|q"),
            TableCell(row=2, col=2, text=""),
        ],
    )
    md = table_markdown(tc)
    assert md.split("\n") == [
        "| A\\|B | C | D |",
        "|---|---|---|",
        "| x y |  |  |",
        "| z | p\\|q |  |",
    ]
    assert not md.endswith("\n")
    assert table_raw_text(tc) == "A|B | C | D\nx y\nz | p|q"
    td = to_table_data(tc, {"docling": (0, 0), "pymupdf": TableShape(rows=3, cols=3)})
    assert td.shape_by_parser["docling"] == TableShape(rows=0, cols=0)
    assert list(td.shape_by_parser) == ["docling", "pymupdf"]
    assert td.markdown == md
