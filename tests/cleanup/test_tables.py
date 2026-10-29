"""Test 9: table reconstruction from TableData (P7)."""

from __future__ import annotations

import pytest

from manuallabor.cleanup.rules import plan_passes
from manuallabor.contracts.block import TableCell, TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.tables import norm_cell, table_markdown_from_data
from manuallabor.scoring.faithfulness import check_faithfulness, parse_gfm
from tests.cleanup.conftest import Proj, det


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
