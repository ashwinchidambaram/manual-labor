"""Test 25: merge behaviour on hand-built candidates."""

from __future__ import annotations

import random

from manuallabor.contracts.block import TableCell
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.merge import merge_page
from manuallabor.parse.types import Line, PageParse, RawBlock, TableCandidate


def _line(text: str, y: float, x0: float = 72, x1: float = 300, i: int = 0) -> Line:
    return Line(text=text, bbox=[x0, y, x1, y + 10], size=10, native_id=f"b0.l{i}")


def _rb(parser: str, order: int, kind: BlockType, lines: list[Line], **kw) -> RawBlock:  # type: ignore[no-untyped-def]
    box = [
        min(ln.bbox[0] for ln in lines),
        min(ln.bbox[1] for ln in lines),
        max(ln.bbox[2] for ln in lines),
        max(ln.bbox[3] for ln in lines),
    ]
    return RawBlock(
        parser=parser,
        page=1,
        order=order,
        bbox=kw.pop("bbox", box),
        kind=kind,
        text="\n".join(ln.text for ln in lines),
        lines=lines,
        **kw,
    )


def _page(blocks: list[RawBlock]) -> PageParse:
    return PageParse(page=1, width=612, height=792, has_text_layer=True, blocks=blocks)


def _merge(p: list[RawBlock], s: list[RawBlock]):  # type: ignore[no-untyped-def]
    return merge_page(_page(p), _page(s), None, 1, names=("pymupdf", "docling", None))


def test_one_to_one() -> None:
    p = [_rb("pymupdf", 0, BlockType.paragraph, [_line("alpha beta", 100)])]
    s = [_rb("docling", 0, BlockType.paragraph, [_line("alpha beta", 101)])]
    blocks, disp = _merge(p, s)
    assert len(blocks) == 1 and blocks[0].raw_source == "pymupdf"
    assert set(blocks[0].text_by_parser) == {"pymupdf", "docling"}
    assert {d.outcome for d in disp} == {"primary", "matched"}


def test_p_split_by_s() -> None:
    lines = [_line("1. Title", 100, i=0), _line("body one", 114, i=1), _line("body two", 126, i=2)]
    p = [_rb("pymupdf", 0, BlockType.paragraph, lines)]
    s = [
        _rb("docling", 0, BlockType.heading, [lines[0]]),
        _rb("docling", 1, BlockType.paragraph, lines[1:]),
    ]
    blocks, disp = _merge(p, s)
    assert [b.raw_text for b in sorted(blocks, key=lambda b: b.primary_key)] == [
        "1. Title",
        "body one\nbody two",
    ]
    assert {d.outcome for d in disp} == {"split"}


def test_s_aligned_onto_p() -> None:
    a = [_line(f"first para line {i}", 100 + 12 * i, i=i) for i in range(3)]
    b = [_line(f"second para line {i}", 140 + 12 * i, i=i) for i in range(3)]
    p = [
        _rb("pymupdf", 0, BlockType.paragraph, a),
        _rb("pymupdf", 1, BlockType.paragraph, b),
    ]
    text = "\n".join(ln.text for ln in a + b).replace("\n", " ")
    whole = _rb(
        "docling",
        0,
        BlockType.paragraph,
        [_line(text, 100)],
        bbox=[72, 100, 300, 174],
    )
    blocks, disp = _merge(p, [whole])
    assert len(blocks) == 2
    got = sorted(blocks, key=lambda m: m.primary_key)
    assert got[0].text_by_parser["docling"].startswith("first para line 0")
    assert got[1].text_by_parser["docling"].endswith("second para line 2")
    assert {d.outcome for d in disp} == {"aligned"}


def test_unmatched_both_kept() -> None:
    p = [_rb("pymupdf", 0, BlockType.paragraph, [_line("only in p", 100)])]
    s = [_rb("docling", 0, BlockType.paragraph, [_line("only in s", 400)])]
    blocks, disp = _merge(p, s)
    assert len(blocks) == 2 and {d.outcome for d in disp} == {"alone"}


def _table() -> TableCandidate:
    cells = [TableCell(row=r, col=c, text=f"r{r}c{c}") for r in range(2) for c in range(2)]
    return TableCandidate(n_rows=2, n_cols=2, cells=cells, header_rows=1)


def test_table_absorbs_cell_text_and_figure_absorbs_labels() -> None:
    tbl = RawBlock(
        parser="pymupdf",
        page=1,
        order=0,
        bbox=[72, 200, 300, 260],
        kind=BlockType.table,
        text="",
        table=_table(),
    )
    cell = _rb("pymupdf", 1, BlockType.paragraph, [_line("r0c0", 205, 76, 120)])
    fig = RawBlock(
        parser="pymupdf",
        page=1,
        order=2,
        bbox=[72, 400, 300, 500],
        kind=BlockType.figure,
        text="",
        image_xrefs=[5],
    )
    label = _rb("pymupdf", 3, BlockType.paragraph, [_line("axis", 450, 100, 140)])
    blocks, disp = _merge([tbl, cell, fig, label], [])
    assert len(blocks) == 2
    t = next(b for b in blocks if b.region == "table")
    f = next(b for b in blocks if b.region == "figure")
    assert t.table is not None and "r1c1" in t.raw_text
    assert f.raw_text == "" and f.text_by_parser["pymupdf"] == "axis"
    assert sum(1 for d in disp if d.outcome == "absorbed") == 2


def test_shuffled_candidates_give_identical_output() -> None:
    p = [
        _rb("pymupdf", i, BlockType.paragraph, [_line(f"text {i}", 100 + 40 * i)]) for i in range(6)
    ]
    s = [
        _rb("docling", i, BlockType.paragraph, [_line(f"text {i}", 100 + 40 * i)]) for i in range(6)
    ]
    base_b, base_d = _merge(p, s)
    for seed in range(3):
        p2, s2 = list(p), list(s)
        random.Random(seed).shuffle(p2)
        random.Random(seed + 10).shuffle(s2)
        b2, d2 = _merge(p2, s2)
        assert [repr(x) for x in b2] == [repr(x) for x in base_b]
        assert d2 == base_d


def test_same_kind_multi_piece_text_in_geometric_order() -> None:
    top = [_line("upper piece one", 100, i=0), _line("upper piece two", 112, i=1)]
    low = [_line(f"lower piece {k}", 130 + 12 * k, i=k) for k in range(4)]
    p = [_rb("pymupdf", 0, BlockType.paragraph, top + low)]
    # Docling emits the big lower piece first (matched 1:1), the small upper one last (absorbed).
    s = [
        _rb("docling", 0, BlockType.paragraph, low),
        _rb("docling", 1, BlockType.paragraph, top),
    ]
    blocks, disp = _merge(p, s)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.text_by_parser["docling"] == "\n".join(ln.text for ln in top + low)
    assert b.text_by_parser["docling"].split() == b.text_by_parser["pymupdf"].split()
    assert b.order_by_parser["docling"] == 0  # the minimum parser index of the pieces
    assert {d.outcome for d in disp} == {"primary", "matched", "absorbed"}


def test_multi_piece_order_is_min_parser_index() -> None:
    a = [_line("piece A on top", 100, i=0)]
    b_ = [_line("piece B in the middle", 120, i=1)]
    c = [_line("piece C at the bottom", 140, i=2)]
    p = [_rb("pymupdf", 0, BlockType.paragraph, a + b_ + c)]
    # Docling delivers C (0), A (1), B (2); A is geometrically first.
    s = [
        _rb("docling", 0, BlockType.paragraph, c),
        _rb("docling", 1, BlockType.paragraph, a),
        _rb("docling", 2, BlockType.paragraph, b_),
    ]
    blocks, _ = _merge(p, s)
    assert len(blocks) == 1
    assert blocks[0].order_by_parser["docling"] == 0


def test_multi_piece_text_is_column_aware() -> None:
    l1 = _line("left one", 100, 72, 280, i=0)
    l2 = _line("left two", 140, 72, 280, i=1)
    r1 = _line("right one", 100, 320, 540, i=2)
    # A PyMuPDF paragraph spans both columns; Docling splits it into per-column pieces.
    p = [_rb("pymupdf", 0, BlockType.paragraph, [l1, l2, r1])]
    s = [
        _rb("docling", 0, BlockType.paragraph, [r1]),
        _rb("docling", 1, BlockType.paragraph, [l2]),
        _rb("docling", 2, BlockType.paragraph, [l1]),
    ]
    blocks, _ = _merge(p, s)
    assert len(blocks) == 1
    assert blocks[0].text_by_parser["docling"] == "left one\nleft two\nright one"
