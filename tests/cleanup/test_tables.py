"""Test 9: table reconstruction from TableData (P7)."""

from __future__ import annotations

from typing import Any

import pytest

from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.rules import plan_passes
from manuallabor.cleanup.types import fallback_detail
from manuallabor.contracts.block import TableCell, TableData, TableShape
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.tables import norm_cell, table_markdown_from_data
from manuallabor.scoring.faithfulness import check_faithfulness, parse_gfm
from manuallabor.scoring.pipeline import score_block
from tests.cleanup.conftest import Proj, det, doc_of
from tests.conftest import ctx as tctx
from tests.conftest import make_block


def _cells(md: str) -> list[list[str]]:
    rows = parse_gfm(md)
    assert rows is not None
    return [[c for c, _ in row] for row in rows]


@pytest.mark.parametrize("slug", ["tables", "manual"])
def test_09_fixture_tables(cleanedproj: Proj, slug: str) -> None:
    blocks = {b.id: b for b in cleanedproj.blocks(slug)}
    tables = [
        e for e in cleanedproj.clean(slug).blocks if blocks[e.block_id].type == BlockType.table
    ]
    assert tables
    for e in tables:
        b = blocks[e.block_id]
        assert b.table is not None
        assert e.passes == ["table"] and e.faith_passed
        assert e.clean_text == table_markdown_from_data(b.table)
        grid = _cells(e.clean_text)
        for c in b.table.cells:
            assert grid[c.row][c.col].strip() == norm_cell(c.text)
    print(f"\n{slug}: {len(tables)} tables reconstructed and verified")


def test_09_fixture_table_count(cleanedproj: Proj) -> None:
    n = sum(
        1
        for s in ("tables", "manual")
        for b in cleanedproj.blocks(s)
        if b.type == BlockType.table and b.table is not None
    )
    assert n == 7


def test_09_pipe_and_spans() -> None:
    td = TableData(
        n_rows=2,
        n_cols=3,
        cells=[
            TableCell(row=0, col=0, col_span=2, text="Part  |  No."),
            TableCell(row=0, col=2, text="Qty"),
            TableCell(row=1, col=0, text="P/N 4471-A"),
            TableCell(row=1, col=1, text=" Belt\n"),
            TableCell(row=1, col=2, text="2"),
        ],
        markdown="",
    )
    md = table_markdown_from_data(td)
    assert md == "| Part \\| No. |  | Qty |\n|---|---|---|\n| P/N 4471-A | Belt | 2 |"
    assert _cells(md)[0] == [" Part | No. ", "  ", " Qty "]
    raw = "Part | No. | Qty\nP/N 4471-A | Belt | 2"
    assert check_faithfulness(raw, md, block_type=BlockType.table, table=td).passed
    assert det(raw, BlockType.table, table=td) == md


def test_09_table_without_tabledata() -> None:
    assert [p.name for p in plan_passes(BlockType.table, False)] == [
        "crlf",
        "unicode",
        "whitespace",
    ]
    raw = "Part  | Qty\r\n\nP/N 4471-A |  2 "
    out = det(raw, BlockType.table)
    assert out == "Part | Qty\nP/N 4471-A | 2"
    assert check_faithfulness(raw, out, block_type=BlockType.table).passed


# -- the rendered grid must cover raw_text (design 2, P7 / scoring 4.3 AE6) ------------------


def _grid(rows: list[list[str]], shapes: dict[str, tuple[int, int]] | None = None) -> TableData:
    shp = shapes or {"pymupdf": (len(rows), 2), "docling": (len(rows), 2)}
    return TableData(
        n_rows=len(rows),
        n_cols=len(rows[0]),
        cells=[
            TableCell(row=r, col=c, text=t, is_header=r == 0)
            for r, row in enumerate(rows)
            for c, t in enumerate(row)
        ],
        markdown="",
        shape_by_parser={k: TableShape(rows=a, cols=b) for k, (a, b) in shp.items()},
    )


ROWS41 = [["Tool", "Use"]] + [[f"Tool{i}x", f"Use{i}y"] for i in range(40)]
ROWS40 = [r for r in ROWS41 if r[0] != "Tool17x"]


def _clean_one(raw: str, td: TableData, texts: dict[str, str] | None = None) -> Any:
    b = make_block(raw, type=BlockType.table, table=td, texts=texts)
    doc = doc_of([b], slug="doc")
    entries, _ = clean_document(doc, [b], [], {b.id}, mode="off")
    assert len(entries) == 1
    return b, entries[0]


@pytest.mark.parametrize("sep", [" | ", " "])
def test_09_structure_missing_a_raw_row_keeps_raw(sep: str) -> None:
    """41 raw rows (one parser), 40 structured rows (the other): the GFM would silently drop a
    row. It is a deletion; cleanup keeps raw_text and the block is queued."""
    raw = "\n".join(sep.join(r) for r in ROWS41)
    td = _grid(ROWS40)
    md = table_markdown_from_data(td)
    r = check_faithfulness(raw, md, block_type=BlockType.table, table=td)
    assert not r.passed
    missing = {v.raw for v in r.violations if v.kind.value == "deletion"}
    assert {"Tool17x", "Use17y"} <= missing, r.violations
    b, e = _clean_one(raw, td, texts={"pymupdf": raw, "docling": md})
    assert e.clean_text == raw
    assert e.passes_rejected == ["table"] and e.fallback and not e.passes
    assert e.faith_passed
    assert e.rejected and e.rejected[0].violations
    s = score_block(
        b.model_copy(update={"clean_text": e.clean_text}),
        tctx(),
        threshold=0.85,
        fallback=fallback_detail(e),
    )
    tc = next(x for x in s.signals if x.name.value == "table_consistency")
    assert tc.critical and tc.value <= 0.5, tc
    assert s.status == "queued"


def test_09_extra_cell_token_is_an_insertion() -> None:
    rows = [["Part", "Torque"], ["Bolt A", "35 N·m"]]
    raw = "Part | Torque\nBolt A | 35 N·m"
    td = _grid([["Part", "Torque"], ["Bolt A", "35 N·m extra"]])
    r = check_faithfulness(raw, table_markdown_from_data(td), block_type=BlockType.table, table=td)
    assert not r.passed and "insertion" in {v.kind.value for v in r.violations}
    td_ok = _grid(rows)
    md = table_markdown_from_data(td_ok)
    assert check_faithfulness(raw, md, block_type=BlockType.table, table=td_ok).passed
    _, e = _clean_one(raw, td_ok)
    assert e.clean_text == md and e.passes == ["table"] and not e.fallback


def test_09_row_count_must_match_detectable_raw_rows() -> None:
    """Same tokens, but the structure merged two raw rows into one: the row count differs
    from the raw rows (`` | `` convention, one row per line)."""
    raw = "Part | Torque\nBolt B | 40 N·m\nBolt C | 45 N·m"
    td = _grid([["Part", "Torque"], ["Bolt B Bolt C", "40 N·m 45 N·m"]])
    r = check_faithfulness(raw, table_markdown_from_data(td), block_type=BlockType.table, table=td)
    assert not r.passed and "deletion" in {v.kind.value for v in r.violations}
    _, e = _clean_one(raw, td)
    assert e.clean_text == raw and e.passes_rejected == ["table"]
