"""Module 10 re-review fixes (round c), pure part: table positions are attested only by
structured cells. A dense reader text drops empty cells, so a short row cannot say which column
each value sits in; padding it to the widest row shifted values left and let a header shift
pass. The inputs are the re-reviewer's attack inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from manuallabor.agent.recheck import (
    build_table_data,
    check_table_consistency,
    check_table_position,
    reader_tables,
)
from manuallabor.contracts.block import TableCell, TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import write_json
from manuallabor.parse.tables import table_markdown_from_data
from manuallabor.parse.types import PageParse, ParserOutput, RawBlock, TableCandidate
from manuallabor.project import ProjectPaths
from tests.conftest import SLUG, make_block


def tb(raw: str, table: TableData | None, **texts: str):  # type: ignore[no-untyped-def]
    b = make_block(raw, type=BlockType.table, source="pymupdf", texts={"pymupdf": raw, **texts})
    return b.model_copy(update={"table": table})


def pos(b: Any, cells: list[list[str]], tables: dict[str, TableData] | None = None) -> Any:
    return check_table_position(b, cells, tables or {}, b.raw_source, True)


# -- the header shift ----------------------------------------------------------------------------

HS_RAW = "Min | Max\nM6 | 10 | 12\nM8 | 20 | 30"
HS_PARSED = [["", "Min", "Max"], ["M6", "10", "12"], ["M8", "20", "30"]]
HS_SHIFTED = [["Min", "Max", ""], ["M6", "10", "12"], ["M8", "20", "30"]]


def test_header_shift_fails_table_position() -> None:
    b = tb(HS_RAW, build_table_data(HS_PARSED, 1), docling=HS_RAW)
    r = pos(b, HS_SHIFTED)
    assert not r.passed, r.detail
    # nor with a structured reader that read the same structure
    assert not pos(b, HS_SHIFTED, {"docling": build_table_data(HS_PARSED, 1)}).passed
    # without a parsed structure the short raw row attests nothing either
    assert not pos(tb(HS_RAW, None, docling=HS_RAW), HS_SHIFTED).passed
    assert pos(b, HS_PARSED).passed


def test_header_row_raggedness_fails_table_consistency() -> None:
    b = tb(HS_RAW, build_table_data(HS_PARSED, 1), docling=HS_RAW)
    r = check_table_consistency(b, build_table_data(HS_SHIFTED, 1))
    assert not r.passed and "ragged" in (r.detail or "")


# -- a body-row shift ----------------------------------------------------------------------------

BR_RAW = "Bolt | Min | Max\nM6 | 12\nM8 | 20 | 30"
BR_PARSED = [["Bolt", "Min", "Max"], ["M6", "", "12"], ["M8", "20", "30"]]
BR_SHIFTED = [["Bolt", "Min", "Max"], ["M6", "12", ""], ["M8", "20", "30"]]


def test_body_row_shift_fails_table_position() -> None:
    b = tb(BR_RAW, build_table_data(BR_PARSED, 1), docling=BR_RAW)
    assert not pos(b, BR_SHIFTED).passed
    assert not pos(b, BR_SHIFTED, {"docling": build_table_data(BR_PARSED, 1)}).passed
    assert not pos(tb(BR_RAW, None, docling=BR_RAW), BR_SHIFTED).passed
    # the short raw row is not a reference for the unshifted cells either
    assert not pos(tb(BR_RAW, None, docling=BR_RAW), BR_PARSED).passed


# -- a legitimate fix, attested by structured cells ----------------------------------------------

LA_RAW = "Part | Torque\nBolt | 1O N·m\nNut | 25 N·m"
LA_CUR = [["Part", "Torque"], ["Bolt", "1O N·m"], ["Nut", "25 N·m"]]
LA_FIXED = [["Part", "Torque"], ["Bolt", "10 N·m"], ["Nut", "25 N·m"]]
LA_OTHER = "Part | Torque\nBolt | 10 N·m\nNut | 25 N·m"


def test_look_alike_fix_with_structured_attestation_passes() -> None:
    b = tb(LA_RAW, build_table_data(LA_CUR, 1), docling=LA_OTHER)
    r = pos(b, LA_FIXED, {"docling": build_table_data(LA_FIXED, 1)})
    assert r.passed, r.detail
    assert "docling" in (r.detail or "")


def test_a_reader_without_structured_cells_attests_nothing() -> None:
    b = tb(LA_RAW, build_table_data(LA_CUR, 1), docling=LA_OTHER)
    assert not pos(b, LA_FIXED).passed  # docling's text alone: no attester
    # the raw source's own structure is not an independent attester
    assert not pos(b, LA_FIXED, {"pymupdf": build_table_data(LA_FIXED, 1)}).passed


# -- merged cells: positions are span-aware ------------------------------------------------------


def _merged(bottom: str) -> TableData:
    td = TableData(
        n_rows=3,
        n_cols=2,
        cells=[
            TableCell(row=0, col=0, text="Model", is_header=True),
            TableCell(row=0, col=1, text="Torque", is_header=True),
            TableCell(row=1, col=0, row_span=2, text="X200"),
            TableCell(row=1, col=1, text="10 N·m"),
            TableCell(row=2, col=1, text=bottom),
        ],
        markdown="|",
    )
    return td.model_copy(update={"markdown": table_markdown_from_data(td)})


def test_fix_under_a_row_span_cell_is_not_refused() -> None:
    raw = "Model | Torque\nX200 | 10 N·m\n2S N·m"
    other = "Model | Torque\nX200 | 10 N·m\n25 N·m"
    b = tb(raw, _merged("2S N·m"), docling=other)
    fixed = [["Model", "Torque"], ["X200", "10 N·m"], ["", "25 N·m"]]
    r = pos(b, fixed, {"docling": _merged("25 N·m")})
    assert r.passed, r.detail
    # the proposal keeps the merged cell: the covered slot is not a ragged row
    td = build_table_data(fixed, 1, base=b.table)
    assert [(c.row, c.col, c.row_span) for c in td.cells if c.row_span > 1] == [(1, 0, 2)]
    assert "ragged" not in (check_table_consistency(b, td).detail or "")
    dense = build_table_data(fixed, 1)
    assert "1 ragged row" in (check_table_consistency(b, dense).detail or "")
    # the dense text of the merged table attests nothing
    assert not pos(b, fixed).passed


# -- reader tables come from the stored per-parser structure -------------------------------------


def _out(parser: str, page: int, order: int, cand: TableCandidate | None) -> ParserOutput:
    rb = RawBlock(
        parser=parser,
        page=page,
        order=order,
        bbox=[0, 0, 10, 10],
        kind=BlockType.table,
        text="",
        table=cand,
    )
    pp = PageParse(page=page, width=100, height=100, has_text_layer=True, blocks=[rb])
    return ParserOutput(parser=parser, version="1", source_sha256="0" * 64, pages=[pp])


def test_reader_tables_load_structured_cells_by_page_and_order(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    dp = paths.doc(SLUG)
    dp.parse_dir.mkdir(parents=True)
    td = build_table_data(LA_FIXED, 1)
    cand = TableCandidate(n_rows=td.n_rows, n_cols=td.n_cols, cells=td.cells, header_rows=1)
    write_json(dp.parser_output("docling"), _out("docling", 1, 2, cand))
    write_json(dp.parser_output("pymupdf"), _out("pymupdf", 1, 0, cand))
    b = make_block(
        LA_RAW,
        type=BlockType.table,
        source="pymupdf",
        texts={"pymupdf": LA_RAW, "docling": LA_OTHER, "ocr": LA_OTHER},
        order={"pymupdf": 0, "docling": 2, "ocr": 0},
    )
    got = reader_tables(paths, SLUG, b)
    assert sorted(got) == ["docling"]  # not the raw source; ocr has no structure
    assert [[c.text for c in got["docling"].cells]] == [[c.text for c in td.cells]]
    # another order on the page is another block: nothing
    b2 = b.model_copy(update={"order_by_parser": {"pymupdf": 0, "docling": 3}})
    assert reader_tables(paths, SLUG, b2) == {}
