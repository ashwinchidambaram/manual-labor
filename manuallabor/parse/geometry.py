"""Rounded rectangle geometry. All boxes are [x0, y0, x1, y1] in PDF points, top-left origin."""

from __future__ import annotations

from collections.abc import Sequence

Box = Sequence[float]


def q(x: float) -> float:
    """Round to 3 decimal places at the adapter boundary (and normalize -0.0)."""
    return round(float(x), 3) + 0.0


def qbox(b: Box) -> list[float]:
    return [q(b[0]), q(b[1]), q(b[2]), q(b[3])]


def width(b: Box) -> float:
    return max(0.0, b[2] - b[0])


def height(b: Box) -> float:
    return max(0.0, b[3] - b[1])


def area(b: Box) -> float:
    return width(b) * height(b)


def intersection(a: Box, b: Box) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def iou(a: Box, b: Box) -> float:
    inter = intersection(a, b)
    if inter <= 0:
        return 0.0
    union_area = area(a) + area(b) - inter
    return inter / union_area if union_area > 0 else 0.0


def contain(a: Box, b: Box) -> float:
    """Fraction of a's area that lies inside b."""
    aa = area(a)
    if aa <= 0:
        # Degenerate box: contained if its center lies inside b.
        cx, cy = center(a)
        return 1.0 if b[0] <= cx <= b[2] and b[1] <= cy <= b[3] else 0.0
    return intersection(a, b) / aa


def union(boxes: Sequence[Box]) -> list[float]:
    return [
        q(min(b[0] for b in boxes)),
        q(min(b[1] for b in boxes)),
        q(max(b[2] for b in boxes)),
        q(max(b[3] for b in boxes)),
    ]


def center(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def expand(b: Box, d: float) -> list[float]:
    return [b[0] - d, b[1] - d, b[2] + d, b[3] + d]


def contains_point(b: Box, x: float, y: float) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]
