"""Heading classification rules (design 01-parse section 4.4)."""

from __future__ import annotations

from manuallabor.contracts.enums import BlockType
from manuallabor.parse.classify import ClassifyInput, classify_blocks
from manuallabor.parse.types import Line


def _item(page: int, text: str, size: float, bold: bool, docling: BlockType | None = None):  # type: ignore[no-untyped-def]
    ln = Line(text=text, bbox=[72, 100, 300, 100 + size], size=size, bold=bold, native_id="l0")
    return ClassifyInput(
        page=page,
        bbox=ln.bbox,
        region="text",
        text=text,
        lines=[ln],
        size=size,
        bold=bold,
        docling_kind=docling,
        docling_level=None,
    )


def test_title_page_subtitle_is_not_a_heading() -> None:
    items = [
        _item(1, "Acme X200 Service Manual", 28, True, BlockType.heading),
        _item(1, "Model X200 · Revision 4", 14, False, BlockType.heading),
        _item(2, "1. Safety", 16, True, BlockType.heading),
        _item(2, "Use only M8 fasteners when refitting the plate and cover.", 10, False),
        _item(2, "Torque the bolts to the listed value before restarting.", 10, False),
    ]
    got = classify_blocks(items, 10.0)
    assert [c.type for c in got] == [
        BlockType.heading,
        BlockType.paragraph,
        BlockType.heading,
        BlockType.paragraph,
        BlockType.paragraph,
    ]
    assert got[2].section_number == "1"


def test_unnumbered_mild_size_bump_is_not_a_heading() -> None:
    items = [
        _item(2, "A slightly larger remark in the body text", 11.0, False, BlockType.heading),
        _item(2, "Use only M8 fasteners when refitting the plate and cover.", 10, False),
        _item(2, "Torque the bolts to the listed value before restarting.", 10, False),
    ]
    assert classify_blocks(items, 10.0)[0].type == BlockType.paragraph
