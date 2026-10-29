"""Test 5: reading_order_risk and the LIS displacement."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.layout import displaced_blocks, lis_keep, reading_order_risk
from tests.scoring.conftest import Scored, make_block


@pytest.mark.parametrize(
    ("seq", "keep"),
    [
        ([], []),
        ([0], [0]),
        ([0, 1, 2, 3], [0, 1, 2, 3]),
        ([0, 2, 1, 3], [0, 2, 3]),  # ties in length: reconstructed from the last pile's top
        ([1, 2, 3, 0], [0, 1, 2]),
        ([3, 0, 1, 2], [1, 2, 3]),
        ([0, 1, 1, 2], [0, 1, 2, 3]),  # non-decreasing: equal values are kept
        ([2, 2, 1, 1], [2, 3]),
    ],
)
def test_lis_keep(seq: list[int], keep: list[int]) -> None:
    assert lis_keep(seq) == keep


def test_values() -> None:
    assert reading_order_risk([], False, 1).value == 1.0
    assert reading_order_risk([], False, None).value == 1.0
    assert reading_order_risk([], False, 2).value == 0.9
    assert reading_order_risk(["docling"], False, 1).value == 0.6
    assert reading_order_risk([], True, 1).value == 0.7
    s = reading_order_risk(["pymupdf"], True, 2)
    assert s.value == pytest.approx(0.6 * 0.7 * 0.9) and not s.critical
    assert s.detail is not None and "displaced in pymupdf order" in s.detail


def test_displacement_excludes_header_footer() -> None:
    blocks = [
        make_block("h", n=1, type=BlockType.header, reading_order=0, order={"pymupdf": 5}),
        make_block("a", n=2, reading_order=1, order={"pymupdf": 0, "docling": 1}),
        make_block("b", n=3, reading_order=2, order={"pymupdf": 2, "docling": 0}),
        make_block("c", n=4, reading_order=3, order={"pymupdf": 3, "docling": 2}),
        make_block("f", n=5, type=BlockType.footer, reading_order=4, order={"pymupdf": 1}),
    ]
    d = displaced_blocks(blocks)
    # docling order [1, 0, 2]: two LIS of length 2; patience sorting keeps the later pile top,
    # so the first body block is the displaced one. The footer's pymupdf 1 is ignored.
    assert d == {"b-doc-p001-02": ["docling"]}


def test_fixture_displacement(scoredproj: Scored) -> None:
    def displaced(slug: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        blocks = scoredproj.blocks(slug)
        for p in sorted({b.page for b in blocks}):
            out.update(displaced_blocks([b for b in blocks if b.page == p]))
        return out

    assert displaced("twocol") == {"b-twocol-p002-09": ["pymupdf"]}
    tables = displaced("tables")
    tb = {b.id: b for b in scoredproj.blocks("tables")}
    assert len(tables) == 5
    assert all(v == ["docling"] and tb[k].type == BlockType.caption for k, v in tables.items())
    assert displaced("clean") == {}
    assert displaced("scanned") == {}
