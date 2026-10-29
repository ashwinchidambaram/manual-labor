"""Test 6: table_consistency."""

from __future__ import annotations

import pytest

from manuallabor.contracts.block import TableCell, TableData, TableShape
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.tables import ragged_rows, table_consistency
from tests.scoring.conftest import Scored


def _table(
    rows: int = 7,
    cols: int = 4,
    shapes: dict[str, tuple[int, int]] | None = None,
    header: bool = True,
    empty: set[tuple[int, int]] | None = None,
) -> TableData:
    empty = empty or set()
    cells = [
        TableCell(
            row=r,
            col=c,
            text="" if (r, c) in empty else f"v{r}{c}",
            is_header=header and r == 0,
        )
        for r in range(rows)
        for c in range(cols)
    ]
    sh = shapes if shapes is not None else {"pymupdf": (rows, cols), "docling": (rows, cols)}
    return TableData(
        n_rows=rows,
        n_cols=cols,
        cells=cells,
        markdown="",
        shape_by_parser={k: TableShape(rows=r, cols=c) for k, (r, c) in sh.items()},
    )


def test_agreeing_with_header() -> None:
    s = table_consistency(_table())
    assert s.value == 1.0 and not s.critical
    assert s.detail is not None and "header ok" in s.detail


def test_shape_disagreement() -> None:
    s = table_consistency(_table(shapes={"pymupdf": (7, 4), "docling": (6, 4)}))
    assert s.value == pytest.approx(6 / 7, abs=1e-6)


def test_no_structure_and_single_parser() -> None:
    assert table_consistency(_table(shapes={"pymupdf": (7, 4), "docling": (0, 0)})).value == 0.5
    assert table_consistency(_table(shapes={"pymupdf": (7, 4)})).value == 0.7


def test_ragged_rows() -> None:
    t = _table(empty={(2, 1), (4, 3)})
    assert ragged_rows(t) == (2, 6)
    assert table_consistency(t).value == pytest.approx(1 - 0.5 * 2 / 6, abs=1e-6)


def test_spans_cover_their_slots() -> None:
    cells = [
        TableCell(row=0, col=0, text="H", is_header=True, col_span=2),
        TableCell(row=1, col=0, text="J1", row_span=2),
        TableCell(row=1, col=1, text="a"),
        TableCell(row=2, col=1, text="b"),
    ]
    t = TableData(n_rows=3, n_cols=2, cells=cells, markdown="")
    assert ragged_rows(t) == (0, 2)


def test_no_header() -> None:
    assert table_consistency(_table(header=False)).value == 0.8


def test_fixture_ragged_table(scoredproj: Scored) -> None:
    vals = [
        table_consistency(b.table).value
        for b in scoredproj.blocks("tables")
        if b.type == BlockType.table and b.table is not None
    ]
    assert len(vals) == 6
    assert min(vals) < 1.0  # the connector table has empty (ragged) body rows
