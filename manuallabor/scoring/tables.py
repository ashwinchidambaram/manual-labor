"""table_consistency: shape agreement, ragged rows, header presence (design 2.6)."""

from __future__ import annotations

from manuallabor.contracts.block import Signal, TableData
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.faithfulness import table_coverage
from manuallabor.scoring.types import (
    TABLE_NO_HEADER,
    TABLE_NO_STRUCTURE,
    TABLE_RAGGED_WEIGHT,
    TABLE_RAW_MISMATCH,
    TABLE_SINGLE_PARSER,
    clamp01,
    truncate,
)


def _shape_term(t: TableData) -> tuple[float, str]:
    shapes = t.shape_by_parser
    desc = ", ".join(f"{k} {s.rows}×{s.cols}" for k, s in sorted(shapes.items()))
    if len(shapes) < 2:
        return TABLE_SINGLE_PARSER, f"shapes {desc or 'none'} (single parser)"
    if any(s.rows == 0 and s.cols == 0 for s in shapes.values()):
        return TABLE_NO_STRUCTURE, f"shapes {desc} (no structure)"
    r, c = t.n_rows, t.n_cols
    vals = [
        (min(s.rows, r) / max(s.rows, r) if max(s.rows, r) else 1.0)
        * (min(s.cols, c) / max(s.cols, c) if max(s.cols, c) else 1.0)
        for _, s in sorted(shapes.items())
    ]
    return min(vals), f"shapes {desc}"


def ragged_rows(t: TableData) -> tuple[int, int]:
    """(ragged body rows, body rows). A row is a header row if a cell starting in it is a
    header cell; a body row is ragged if fewer than n_cols grid slots are covered by
    non-empty cells."""
    covered = [[False] * t.n_cols for _ in range(t.n_rows)]
    header_rows: set[int] = set()
    for cell in t.cells:
        if cell.is_header:
            header_rows.add(cell.row)
        if not cell.text.strip():
            continue
        for r in range(cell.row, cell.row + cell.row_span):
            for c in range(cell.col, cell.col + cell.col_span):
                covered[r][c] = True
    body = [r for r in range(t.n_rows) if r not in header_rows]
    ragged = sum(1 for r in body if sum(covered[r]) < t.n_cols)
    return ragged, len(body)


def cell_rows(t: TableData) -> list[list[str]]:
    """Cell texts per grid row (origin cells only, column order)."""
    rows: list[list[str]] = [[] for _ in range(t.n_rows)]
    for cell in sorted(t.cells, key=lambda c: (c.row, c.col)):
        if cell.row < t.n_rows:
            rows[cell.row].append(cell.text)
    return rows


def table_consistency(t: TableData, raw: str | None = None) -> Signal:
    """Shape agreement x ragged rows x header presence. With ``raw`` (the block's raw_text),
    cells that do not cover raw_text (a token or a row of raw missing from the structure, or
    extra; faithfulness ``table_coverage``) make the signal critical at TABLE_RAW_MISMATCH:
    the structure came from a parser that read the table differently, so it is reviewed."""
    shape, shape_desc = _shape_term(t)
    ragged, body = ragged_rows(t)
    ragged_term = 1 - TABLE_RAGGED_WEIGHT * ragged / max(1, body)
    has_header = any(c.is_header for c in t.cells)
    header_term = 1.0 if has_header else TABLE_NO_HEADER
    value = clamp01(shape * ragged_term * header_term)
    detail = (
        f"{shape_desc}; {ragged} ragged row{'s' if ragged != 1 else ''}; "
        f"{'header ok' if has_header else 'no header'}"
    )
    critical = False
    if raw is not None:
        cov = table_coverage(raw, cell_rows(t))
        if not cov.ok:
            value = min(value, TABLE_RAW_MISMATCH)
            critical = True
            detail = f"cells disagree with raw text: {cov.detail()}; {detail}"
    return Signal(
        name=SignalName.table_consistency, value=value, critical=critical, detail=truncate(detail)
    )
