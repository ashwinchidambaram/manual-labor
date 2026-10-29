"""Test 23: reading order and column detection."""

from __future__ import annotations

import random

from manuallabor.parse.layout import OrderItem, order_page


def _run(spec: list[tuple[str, list[float], str]], shuffle: int | None = None) -> list[str]:
    items = list(enumerate(spec))
    if shuffle is not None:
        random.Random(shuffle).shuffle(items)
    order_items = [OrderItem(bbox=s[1], role=s[2], tiebreak=(i,)) for i, s in items]  # type: ignore[arg-type]
    seq, _ = order_page(order_items, 612, 792)
    return [items[k][1][0] for k in seq]


def _box(x0: float, y0: float, w: float = 220, h: float = 40) -> list[float]:
    return [x0, y0, x0 + w, y0 + h]


def test_one_column() -> None:
    spec = [(f"p{i}", _box(72, 100 + 60 * i, 468), "body") for i in range(4)]
    assert _run(spec, 1) == ["p0", "p1", "p2", "p3"]


def test_two_columns_with_spanning_heading() -> None:
    spec = [
        ("head", _box(72, 80, 468, 20), "body"),
        ("l1", _box(72, 120), "body"),
        ("l2", _box(72, 200), "body"),
        ("r1", _box(320, 120), "body"),
        ("r2", _box(320, 200), "body"),
        ("hdr", _box(72, 30, 100, 10), "header"),
        ("ftr", _box(72, 750, 40, 10), "footer"),
    ]
    want = ["hdr", "head", "l1", "l2", "r1", "r2", "ftr"]
    assert _run(spec) == want
    assert _run(spec, 7) == want


def test_three_columns() -> None:
    spec = []
    for c, x in enumerate((72, 230, 388)):
        for r in range(2):
            spec.append((f"c{c}r{r}", _box(x, 100 + 90 * r, 140), "body"))
    assert _run(spec, 3) == ["c0r0", "c0r1", "c1r0", "c1r1", "c2r0", "c2r1"]


def test_narrow_gutter_does_not_split() -> None:
    spec = [
        ("a", _box(72, 100, 226), "body"),
        ("b", _box(306, 100, 226), "body"),  # 8 pt gap
        ("c", _box(72, 200, 226), "body"),
        ("d", _box(306, 200, 226), "body"),
    ]
    assert _run(spec, 5) == ["a", "b", "c", "d"]


def _ln(text: str, y: float, x1: float, size: float, i: int):  # type: ignore[no-untyped-def]
    from manuallabor.parse.types import Line

    return Line(text=text, bbox=[72, y, x1, y + size + 3], size=size, native_id=f"l{i}")


def test_heading_line_breaks_out_of_paragraph_with_tight_spacing() -> None:
    from manuallabor.parse.layout import group_lines_into_blocks

    lines = [
        _ln("2.2 Tension Adjustment", 72, 207, 8.0, 0),  # same size, numbered, short
        _ln("Replace the coolant reservoir if it shows any sign of", 87, 520, 8.0, 1),
        _ln("deformation. The control circuit runs from a 12 V supply,", 101, 520, 8.0, 2),
        _ln("so disconnect it.", 115, 200, 8.0, 3),
        _ln("Large Title", 140, 200, 11.0, 4),  # >= 1.25x the page's median size
        _ln("Compare the coolant reservoir against the reference", 160, 520, 8.0, 5),
        _ln("illustration before refitting the cover plate.", 174, 520, 8.0, 6),
    ]
    groups = group_lines_into_blocks(lines, 612)
    assert [[ln.text for ln in g][0] for g in groups] == [
        "2.2 Tension Adjustment",
        "Replace the coolant reservoir if it shows any sign of",
        "Large Title",
        "Compare the coolant reservoir against the reference",
    ]
    assert [len(g) for g in groups] == [1, 3, 1, 2]
