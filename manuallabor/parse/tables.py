"""Table structure: PyMuPDF/Docling converters, Markdown, raw text (design section 9)."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from typing import Any

from manuallabor.contracts.block import TableCell, TableData, TableShape
from manuallabor.parse.types import TableCandidate

_WS = re.compile(r"\s+")


def _norm(text: str | None) -> str:
    return _WS.sub(" ", text or "").strip()


def norm_cell(text: str | None) -> str:
    """Cell text normalization used everywhere a cell is rendered: whitespace runs to one
    space, ends stripped. Nothing else is ever changed in a cell."""
    return _norm(text)


# --------------------------------------------------------------------------- PyMuPDF


def _edge_index(edges: list[float], value: float) -> int:
    """Index of the grid edge nearest to ``value`` (edges sorted ascending)."""
    i = bisect_left(edges, value)
    if i == 0:
        return 0
    if i == len(edges):
        return len(edges) - 1
    return i if edges[i] - value < value - edges[i - 1] else i - 1


def _cluster(values: list[float], tol: float = 1.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def _word_text(words: Sequence[Any], rect: Sequence[float]) -> str:
    """Text of the page words whose center lies in ``rect`` (reading order by native indices)."""
    hit = []
    for w in words:
        cx = (w[0] + w[2]) / 2.0
        cy = (w[1] + w[3]) / 2.0
        if rect[0] <= cx < rect[2] and rect[1] <= cy < rect[3]:
            hit.append(w)
    hit.sort(key=lambda w: (w[5], w[6], w[7], w[0]))
    return _norm(" ".join(str(w[4]) for w in hit))


def _spans_from_geometry(
    rows: Sequence[Any], n_rows: int, n_cols: int
) -> dict[tuple[int, int], tuple[int, int]] | None:
    """(row, col) -> (row_span, col_span) from cell rectangles, or None if the grid is unclear."""
    boxes = [
        (r, c, cell)
        for r, row in enumerate(rows)
        for c, cell in enumerate(row.cells)
        if cell is not None
    ]
    xs = _cluster([b[2][0] for b in boxes] + [b[2][2] for b in boxes])
    ys = _cluster([b[2][1] for b in boxes] + [b[2][3] for b in boxes])
    if len(xs) != n_cols + 1 or len(ys) != n_rows + 1:
        return None
    out: dict[tuple[int, int], tuple[int, int]] = {}
    for r, c, box in boxes:
        c0, c1 = _edge_index(xs, box[0]), _edge_index(xs, box[2])
        r0, r1 = _edge_index(ys, box[1]), _edge_index(ys, box[3])
        if (r0, c0) != (r, c) or r1 <= r0 or c1 <= c0:
            return None
        out[(r, c)] = (r1 - r0, c1 - c0)
    return out


def _spans_from_gaps(
    rows: Sequence[Any], n_rows: int, n_cols: int
) -> dict[tuple[int, int], tuple[int, int]]:
    """Fallback: a None cell belongs to the nearest origin to its left, else above."""
    out: dict[tuple[int, int], tuple[int, int]] = {}
    present = [[cell is not None for cell in row.cells] for row in rows]
    for r in range(n_rows):
        for c in range(n_cols):
            if not present[r][c]:
                continue
            cs = 1
            while c + cs < n_cols and not present[r][c + cs]:
                cs += 1
            rs = 1
            while r + rs < n_rows and not present[r + rs][c]:
                rs += 1
            out[(r, c)] = (rs, cs)
    return out


def header_rows_of(cells: Sequence[TableCell], n_rows: int, external: bool) -> int:
    """Header rows from row-0 spans, counted from row 0 downward and capped at n_rows - 1."""
    if external:
        return 0
    deepest = max((c.row + c.row_span for c in cells if c.row == 0), default=0)
    return max(0, min(deepest, n_rows - 1))


def from_pymupdf(tab: Any, page: Any | None = None) -> TableCandidate:
    """Convert a ``pymupdf.table.Table`` into a TableCandidate.

    Cell text is taken from the page words inside each cell (``Table.extract`` drops spaces in
    some PDFs); without a page it falls back to ``tab.extract()``.
    """
    n_rows = int(tab.row_count)
    n_cols = int(tab.col_count)
    rows = list(tab.rows)
    spans = _spans_from_geometry(rows, n_rows, n_cols) or _spans_from_gaps(rows, n_rows, n_cols)
    words: list[Any] | None = None
    if page is not None:
        words = list(page.get_text("words"))
    extracted = tab.extract() if words is None or not words else None

    cells: list[TableCell] = []
    for (r, c), (rs, cs) in sorted(spans.items()):
        rect = rows[r].cells[c]
        if extracted is not None:
            text = _norm(extracted[r][c] if r < len(extracted) and c < len(extracted[r]) else "")
        else:
            assert words is not None
            text = _word_text(words, rect)
        cells.append(TableCell(row=r, col=c, row_span=rs, col_span=cs, text=text))
    header_rows = header_rows_of(
        cells, n_rows, external=bool(getattr(tab.header, "external", False))
    )
    cells = [cell.model_copy(update={"is_header": cell.row < header_rows}) for cell in cells]
    return TableCandidate(n_rows=n_rows, n_cols=n_cols, cells=cells, header_rows=header_rows)


# --------------------------------------------------------------------------- Docling


def from_docling(item: Any) -> TableCandidate:
    """Convert a docling ``TableItem`` into a TableCandidate (empty cells fill uncovered slots)."""
    data = item.data
    raw = list(data.table_cells)
    n_rows = max([int(data.num_rows)] + [int(tc.end_row_offset_idx) for tc in raw] + [1])
    n_cols = max([int(data.num_cols)] + [int(tc.end_col_offset_idx) for tc in raw] + [1])

    by_origin: dict[tuple[int, int], TableCell] = {}
    header_rows = 0
    for tc in sorted(
        raw,
        key=lambda t: (
            int(t.start_row_offset_idx),
            int(t.start_col_offset_idx),
            -int(t.end_row_offset_idx),
            -int(t.end_col_offset_idx),
        ),
    ):
        r, c = int(tc.start_row_offset_idx), int(tc.start_col_offset_idx)
        rs = max(1, min(int(tc.end_row_offset_idx) - r, n_rows - r))
        cs = max(1, min(int(tc.end_col_offset_idx) - c, n_cols - c))
        is_header = bool(getattr(tc, "column_header", False))
        text = _norm(getattr(tc, "text", ""))
        prev = by_origin.get((r, c))
        if prev is not None:
            if not prev.text and text:
                by_origin[(r, c)] = prev.model_copy(update={"text": text})
            continue
        by_origin[(r, c)] = TableCell(
            row=r, col=c, row_span=rs, col_span=cs, text=text, is_header=is_header
        )
        if is_header and r == 0:
            header_rows = max(header_rows, r + rs)
    # Same cap as the PyMuPDF path (header_rows_of): never every row.
    header_rows = max(0, min(header_rows, n_rows - 1))

    covered = [[False] * n_cols for _ in range(n_rows)]
    for (r, c), cell in sorted(by_origin.items()):
        for rr in range(r, r + cell.row_span):
            for cc in range(c, c + cell.col_span):
                covered[rr][cc] = True
    for r in range(n_rows):
        for c in range(n_cols):
            if not covered[r][c]:
                by_origin[(r, c)] = TableCell(row=r, col=c, text="", is_header=r < header_rows)
    cells = [
        c.model_copy(update={"is_header": c.row < header_rows})
        for c in (by_origin[k] for k in sorted(by_origin))
    ]
    return TableCandidate(n_rows=n_rows, n_cols=n_cols, cells=cells, header_rows=header_rows)


# --------------------------------------------------------------------------- rendering


def table_raw_text(tc: TableCandidate) -> str:
    """Per row, non-empty cell texts joined `` | ``; rows joined by newline (GT convention)."""
    by_row: dict[int, list[TableCell]] = {}
    for cell in sorted(tc.cells, key=lambda x: (x.row, x.col)):
        by_row.setdefault(cell.row, []).append(cell)
    lines = []
    for r in sorted(by_row):
        parts = [_norm(c.text) for c in by_row[r] if _norm(c.text)]
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _md_cell(text: str) -> str:
    return _norm(text).replace("|", "\\|")


def _markdown(n_rows: int, n_cols: int, cells: Sequence[TableCell]) -> str:
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for cell in cells:
        if cell.row < n_rows and cell.col < n_cols:
            grid[cell.row][cell.col] = _md_cell(cell.text)
    lines = ["| " + " | ".join(grid[0]) + " |", "|" + "---|" * n_cols]
    lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
    return "\n".join(lines)


def table_markdown(tc: TableCandidate) -> str:
    """GFM table: row 0 header, separator, remaining rows; n_rows + 1 lines, no trailing newline."""
    return _markdown(tc.n_rows, tc.n_cols, tc.cells)


def table_markdown_from_data(td: TableData) -> str:
    """The same GFM as ``table_markdown``, rendered from stored TableData: covered span slots
    are empty, ``|`` is escaped, cell text is only ``norm_cell``ed."""
    return _markdown(td.n_rows, td.n_cols, td.cells)


def shape_of(tc: TableCandidate) -> TableShape:
    return TableShape(rows=tc.n_rows, cols=tc.n_cols)


def to_table_data(
    primary: TableCandidate, shapes: Mapping[str, TableShape | tuple[int, int]]
) -> TableData:
    """Build the contract TableData from the primary structure and per-parser shapes."""
    cells = sorted(primary.cells, key=lambda x: (x.row, x.col))
    shape_by_parser = {
        k: v if isinstance(v, TableShape) else TableShape(rows=v[0], cols=v[1])
        for k, v in sorted(shapes.items())
    }
    return TableData(
        n_rows=primary.n_rows,
        n_cols=primary.n_cols,
        cells=cells,
        markdown=table_markdown(primary),
        shape_by_parser=shape_by_parser,
    )


__all__ = [
    "from_docling",
    "from_pymupdf",
    "norm_cell",
    "shape_of",
    "table_markdown",
    "table_markdown_from_data",
    "table_raw_text",
    "to_table_data",
]
