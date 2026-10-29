"""Reading order, column detection and line grouping (design 01-parse section 5)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from manuallabor.parse import geometry as g
from manuallabor.parse.text import BULLETS, SECTION_RE
from manuallabor.parse.types import Band, Line

SPAN_FRACTION = 0.55
GUTTER_PT = 10.0
PITCH_FACTOR = 1.09
PITCH_QUANTILE = 0.25
HEADING_SIZE_FACTOR = 1.25
HEADING_MAX_WIDTH_FRAC = 0.6
HEADING_MAX_WORDS = 12


@dataclass(frozen=True)
class OrderItem:
    bbox: Sequence[float]
    role: Literal["header", "footer", "body"]
    tiebreak: tuple[int, ...] = ()


def _spanning_flags(boxes: Sequence[Sequence[float]]) -> list[bool]:
    if not boxes:
        return []
    extent = max(b[2] for b in boxes) - min(b[0] for b in boxes)
    return [(b[2] - b[0]) >= SPAN_FRACTION * extent for b in boxes]


def _column_intervals(boxes: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """Columns of one band: intervals separated by zero-coverage gutters >= GUTTER_PT."""
    lo = min(b[0] for b in boxes)
    hi = max(b[2] for b in boxes)
    n = max(1, int(hi - lo) + 1)
    cov = [0] * n
    for b in boxes:
        a = int(max(0.0, b[0] - lo))
        z = int(min(float(n), b[2] - lo + 1.0))
        for i in range(a, max(a + 1, z)):
            cov[min(i, n - 1)] += 1
    cuts: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if cov[i] == 0:
            j = i
            while j < n and cov[j] == 0:
                j += 1
            if j - i >= GUTTER_PT and i > 0 and j < n:
                cuts.append((i, j))
            i = j
        else:
            i += 1
    cols: list[tuple[float, float]] = []
    start = lo
    for a, b2 in cuts:
        cols.append((start, lo + a))
        start = lo + b2
    cols.append((start, hi))
    return cols


def _column_of(cols: list[tuple[float, float]], x: float) -> int:
    for k, (a, b) in enumerate(cols):
        if a <= x <= b:
            return k
    # in a gutter: nearest column
    return min(range(len(cols)), key=lambda k: min(abs(x - cols[k][0]), abs(x - cols[k][1])))


def _bands(
    boxes: Sequence[Sequence[float]],
) -> tuple[list[bool], list[int], dict[int, list[tuple[float, float]]]]:
    """(spanning flags, band index per item, column intervals per band)."""
    span = _spanning_flags(boxes)
    span_y0 = sorted(b[1] for b, s in zip(boxes, span, strict=True) if s)
    band_of: list[int] = []
    for b, s in zip(boxes, span, strict=True):
        k = sum(1 for y in span_y0 if y <= b[1] + 1e-6)
        if s:
            k = sum(1 for y in span_y0 if y < b[1] - 1e-6)  # spanning items sit above their band
        band_of.append(k)
    cols: dict[int, list[tuple[float, float]]] = {}
    for k in sorted(set(band_of)):
        members = [b for b, s, bk in zip(boxes, span, band_of, strict=True) if bk == k and not s]
        if members:
            cols[k] = _column_intervals(members)
    return span, band_of, cols


def detect_columns(boxes: Sequence[Sequence[float]], page_w: float) -> list[Band]:
    """Bands (runs between spanning items) that hold non-spanning items, with their columns."""
    if not boxes:
        return []
    span, band_of, cols = _bands(boxes)
    out: list[Band] = []
    for k in sorted(cols):
        members = [b for b, s, bk in zip(boxes, span, band_of, strict=True) if bk == k and not s]
        out.append(
            Band(
                y0=g.q(min(b[1] for b in members)),
                y1=g.q(max(b[3] for b in members)),
                columns=[[g.q(a), g.q(z)] for a, z in cols[k]],
            )
        )
    return out


def order_page_ex(
    items: Sequence[OrderItem], page_w: float, page_h: float
) -> tuple[list[int], list[Band], list[int]]:
    """(order, bands, column index per item). ``order`` lists item indices in reading order."""
    del page_w, page_h
    headers = [i for i, it in enumerate(items) if it.role == "header"]
    footers = [i for i, it in enumerate(items) if it.role == "footer"]
    body = [i for i, it in enumerate(items) if it.role == "body"]

    def hf_key(i: int) -> tuple[float, float, tuple[int, ...]]:
        b = items[i].bbox
        return (round(b[1], 1), round(b[0], 1), items[i].tiebreak)

    headers.sort(key=hf_key)
    footers.sort(key=hf_key)
    col_idx = [0] * len(items)
    order: list[int] = list(headers)
    bands_out: list[Band] = []
    if body:
        boxes = [items[i].bbox for i in body]
        span, band_of, cols = _bands(boxes)
        # sequence key: (band, 1=column item / 2=spanning item closing the band, ...)
        keyed: list[tuple[tuple[object, ...], int]] = []
        for local, i in enumerate(body):
            b = items[i].bbox
            k = band_of[local]
            if span[local]:
                keyed.append(((k, 2, 0, round(b[1], 1), round(b[0], 1), items[i].tiebreak), i))
            else:
                c = _column_of(cols[k], (b[0] + b[2]) / 2.0)
                col_idx[i] = c
                keyed.append(((k, 1, c, round(b[1], 1), round(b[0], 1), items[i].tiebreak), i))
        keyed.sort(key=lambda t: t[0])
        order.extend(i for _, i in keyed)
        bands_out = detect_columns(boxes, 0.0)
    order.extend(footers)
    return order, bands_out, col_idx


def order_page(
    items: Sequence[OrderItem], page_w: float, page_h: float
) -> tuple[list[int], list[Band]]:
    order, bands, _ = order_page_ex(items, page_w, page_h)
    return order, bands


# ---------------------------------------------------------------------------------------------
# Lines -> blocks (used for OCR)


def _baseline(ln: Line) -> float:
    """Median word bottom (robust to descenders); the line's bottom when it has no words."""
    ys = [w.bbox[3] for w in ln.words if w.bbox is not None]
    return statistics.median(ys) if ys else ln.bbox[3]


def _typical_pitch(pitches: Sequence[float]) -> float | None:
    """The within-paragraph line pitch: a low quantile, so paragraph breaks do not inflate it."""
    if len(pitches) < 3:
        return None
    ordered = sorted(pitches)
    return ordered[min(len(ordered) - 1, int(PITCH_QUANTILE * len(ordered)))]


def is_bullet_line(text: str) -> bool:
    t = text.lstrip()
    return len(t) >= 2 and t[0] in BULLETS and t[1] == " "


def is_heading_line(ln: Line, med_size: float, column_width: float) -> bool:
    """A short line that is clearly larger than the page's lines, or a short numbered title."""
    if column_width <= 0 or (ln.bbox[2] - ln.bbox[0]) >= HEADING_MAX_WIDTH_FRAC * column_width:
        return False
    text = ln.text.strip()
    if not text or len(text.split()) > HEADING_MAX_WORDS or text.endswith("."):
        return False
    if SECTION_RE.match(text):
        return True
    size = ln.size if ln.size else (ln.bbox[3] - ln.bbox[1])
    return med_size > 0 and size >= HEADING_SIZE_FACTOR * med_size


def group_lines_into_blocks(lines: Sequence[Line], page_w: float) -> list[list[Line]]:
    if not lines:
        return []
    boxes = [ln.bbox for ln in lines]
    span, band_of, cols = _bands(boxes)
    keyed: list[tuple[tuple[object, ...], int]] = []
    for i, ln in enumerate(lines):
        b = ln.bbox
        k = band_of[i]
        if span[i]:
            c = 0
            kk: tuple[object, ...] = (k, 2, 0, round(b[1], 1), round(b[0], 1), ln.native_id)
        else:
            c = _column_of(cols[k], (b[0] + b[2]) / 2.0)
            kk = (k, 1, c, round(b[1], 1), round(b[0], 1), ln.native_id)
        keyed.append((kk, i))
    keyed.sort(key=lambda t: t[0])
    seq = [lines[i] for _, i in keyed]
    col_key: list[tuple[object, ...]] = []
    for kk, i in keyed:
        if span[i] or len(cols.get(band_of[i], [])) <= 1:
            col_key.append(("S",))  # single-column flow: line spacing rules decide the blocks
        else:
            col_key.append((kk[0], kk[2]))

    def height(ln: Line) -> float:
        return ln.size if ln.size else (ln.bbox[3] - ln.bbox[1])

    sizes = [ln.size if ln.size else (ln.bbox[3] - ln.bbox[1]) for ln in lines]
    med_size = statistics.median(sizes)
    groups: list[list[Line]] = []
    start = 0
    # Walk contiguous runs sharing (band, kind, column); a spanning line is its own run.
    runs: list[tuple[int, int]] = []
    for i in range(1, len(seq) + 1):
        if i == len(seq) or col_key[i] != col_key[start]:
            runs.append((start, i))
            start = i
    for a, z in runs:
        run = seq[a:z]
        heights = [ln.bbox[3] - ln.bbox[1] for ln in run]
        med_h = statistics.median(heights)
        centers = [_baseline(ln) for ln in run]
        pitches = [y1 - y0 for y0, y1 in zip(centers, centers[1:], strict=False) if y1 > y0]
        med_pitch = _typical_pitch(pitches)
        run_w = max(ln.bbox[2] for ln in run) - min(ln.bbox[0] for ln in run)
        heading = [is_heading_line(ln, med_size, run_w) for ln in run]
        cur: list[Line] = [run[0]]
        for k, (prev, ln) in enumerate(zip(run, run[1:], strict=False), start=1):
            gap = ln.bbox[1] - prev.bbox[3]
            pitch = _baseline(ln) - _baseline(prev)
            hp, hc = height(prev), height(ln)
            starts_bullets = (
                is_bullet_line(ln.text)
                and not is_bullet_line(cur[-1].text)
                and not any(is_bullet_line(c.text) for c in cur)
            )
            spacing_break = gap > 0.8 * med_h or (
                med_pitch is not None and pitch > PITCH_FACTOR * med_pitch
            )
            size_break = hp > 0 and abs(hc - hp) / hp > 0.25
            new = spacing_break or size_break or starts_bullets or heading[k] or heading[k - 1]
            if not new and any(is_bullet_line(c.text) for c in cur) and not is_bullet_line(ln.text):
                first_bullet = next(c for c in cur if is_bullet_line(c.text))
                if ln.bbox[0] < first_bullet.bbox[0] + 2.0:
                    new = True
            if new:
                groups.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        groups.append(cur)
    return groups
