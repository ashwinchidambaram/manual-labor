"""Test 25: merge behaviour on hand-built candidates."""

from __future__ import annotations

import random

import pytest

from manuallabor.contracts.block import TableCell
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.merge import is_running_text, merge_page, split_figure_text
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


# -- scanned pages: running text inside a figure region is not swallowed by the figure --------


def _w(text: str, x0: float, y: float, w: float | None = None, h: float = 8.0):  # type: ignore[no-untyped-def]
    from manuallabor.contracts.block import OcrWord

    return OcrWord(text=text, confidence=0.95, bbox=[x0, y, x0 + (w or 5.0 * len(text)), y + h])


def _ocr_line(words, i: int) -> Line:  # type: ignore[no-untyped-def]
    return Line(
        text=" ".join(w.text for w in words),
        bbox=[
            min(w.bbox[0] for w in words),
            min(w.bbox[1] for w in words),
            max(w.bbox[2] for w in words),
            max(w.bbox[3] for w in words),
        ],
        size=8,
        words=list(words),
        native_id=f"ocr.l{i}",
    )


def _scan_page(blocks: list[RawBlock]) -> PageParse:
    return PageParse(page=1, width=612, height=792, has_text_layer=False, blocks=blocks)


FIG_BOX = [180.0, 120.0, 480.0, 455.0]
PARA = [
    "Having observed on",
    "gauge 57 P.S.I.=",
    "21,000 ft.lb. and",
    "counted 10 blows per",
    "inch, bearing will",
    "be 105 tons.",
]


def _chart_with_paragraph() -> list[Line]:
    """OCR lines of a scanned chart: axis ticks at x~205 share text lines with a paragraph
    printed inside the chart at x~360 (the real manual's p16 bearing curve)."""
    lines = [_ocr_line([_w("40", 208, 200)], 0), _ocr_line([_w("50", 208, 225)], 1)]
    y = 387.0
    for i, text in enumerate(PARA):
        words = []
        x = 362.0
        if i in (1, 3):
            words += [_w("120" if i == 1 else "130", 203, y), _w("4", 222, y)]
        for t in text.split():
            words.append(_w(t, x, y))
            x += 5.0 * len(t) + 5.0
        lines.append(_ocr_line(words, i + 2))
        y += 10.0
    return lines


def _figure_rb() -> RawBlock:
    return RawBlock(parser="docling", page=1, order=0, bbox=FIG_BOX, kind=BlockType.figure, text="")


def test_scanned_running_text_inside_figure_becomes_own_block() -> None:
    lines = _chart_with_paragraph()
    blob = _rb("ocr", 0, BlockType.paragraph, lines)
    alt = [
        _rb(
            "ocr_alt",
            0,
            BlockType.paragraph,
            [_ocr_line([_w("Having", 367, 387), _w("observed", 400, 387), _w("on", 445, 387)], 0)],
        ),
        _rb("ocr_alt", 1, BlockType.paragraph, [_ocr_line([_w("40", 208, 200)], 1)]),
    ]
    blocks, disp = merge_page(
        _scan_page([blob]),
        _scan_page(alt),
        _scan_page([_figure_rb()]),
        1,
        names=("ocr", "ocr_alt", "docling"),
        scanned=True,
    )
    fig = next(b for b in blocks if b.region == "figure")
    texts = [b for b in blocks if b.region == "text"]
    assert len(texts) == 1, [b.raw_text for b in blocks]
    t = texts[0]
    assert t.raw_source == "ocr" and t.raw_text == "\n".join(PARA)
    assert t.ocr_words is not None and [w.text for w in t.ocr_words] == " ".join(PARA).split()
    assert t.bbox == [362.0, 387.0, max(w.bbox[2] for w in t.ocr_words), 445.0]
    assert t.text_by_parser["ocr_alt"] == "Having observed on"
    assert fig.bbox == FIG_BOX and fig.raw_text == ""
    assert "gauge" not in fig.text_by_parser["ocr"] and "120 4" in fig.text_by_parser["ocr"]
    assert fig.text_by_parser["ocr_alt"] == "40"
    assert {(d.parser, d.order): d.outcome for d in disp}[("ocr", 0)] == "split"


def test_scanned_figure_labels_stay_absorbed() -> None:
    """Axis ticks, single labels and one caption-like line (>= 8 words but 1 line) are figure
    content, not running text."""
    lines = [
        _ocr_line(
            [
                _w(t, 205 + 30 * k, 180)
                for k, t in enumerate(["30", "20", "18", "16", "14", "12", "10", "8"])
            ],
            0,
        ),
        _ocr_line([_w(t, 205, 200 + 25 * k) for k, t in enumerate(["40"])], 1),
        _ocr_line(
            [_w("BLOWS", 302, 165, 24), _w("PER", 337, 165, 16), _w("INCH", 364, 165, 20)], 2
        ),
        _ocr_line(
            [
                _w(t, 200 + 26 * k, 300)
                for k, t in enumerate(
                    ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
                )
            ],
            3,
        ),
    ]
    blob = _rb("ocr", 0, BlockType.paragraph, lines)
    blocks, disp = merge_page(
        _scan_page([blob]),
        None,
        _scan_page([_figure_rb()]),
        1,
        names=("ocr", None, "docling"),
        scanned=True,
    )
    assert [b.region for b in blocks] == ["figure"]
    assert {d.outcome for d in disp if d.parser == "ocr"} == {"absorbed"}


def test_scanned_running_text_spread_over_line_candidates() -> None:
    """The OCR grouper can emit each chart line as its own candidate (real manual p16): the
    paragraph is assembled across them, label-only candidates stay with the figure."""
    lines = _chart_with_paragraph()
    cands = [_rb("ocr", i, BlockType.paragraph, [ln]) for i, ln in enumerate(lines)]
    blocks, disp = merge_page(
        _scan_page(cands),
        None,
        _scan_page([_figure_rb()]),
        1,
        names=("ocr", None, "docling"),
        scanned=True,
    )
    texts = [b for b in blocks if b.region == "text"]
    assert len(texts) == 1 and texts[0].raw_text == "\n".join(PARA)
    assert texts[0].order_by_parser == {"ocr": 2}
    out = {(d.parser, d.order): d.outcome for d in disp}
    assert out[("ocr", 0)] == out[("ocr", 1)] == "absorbed"  # tick labels 40, 50
    assert out[("ocr", 2)] == "primary"
    assert out[("ocr", 3)] == "split" and out[("ocr", 5)] == "split"  # 120 4 / 130 4 + text
    assert out[("ocr", 4)] == out[("ocr", 6)] == out[("ocr", 7)] == "matched"
    fig = next(b for b in blocks if b.region == "figure")
    assert fig.text_by_parser["ocr"] == "40\n50\n120 4\n130 4"


# -- figure-text release rule (module 3 second review) ----------------------------------------


def _fig_line(text: str, y: float, i: int, x0: float = 50.0) -> Line:
    words = []
    x = x0
    for t in text.split():
        words.append(_w(t, x, y, h=10.0))
        x += 5.0 * len(t) + 4.0
    return _ocr_line(words, i)


def _stack(texts: list[str]) -> list[Line]:
    return [_fig_line(t, 100.0 + 12.0 * k, k) for k, t in enumerate(texts)]


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]


@pytest.mark.parametrize(
    "texts",
    [
        MONTHS,  # stacked axis labels, one word a line
        ["Oil pressure", "Coolant temp", "Fuel level", "Battery voltage"],  # 4x2 legend
        ["1 Bolt", "2 Nut", "3 Washer", "4 Gasket", "5 Cover", "6 Clamp"],  # callout key
        ["1. Clamp, loop", "2. Strainer", "3. Ring, retaining", "4. Valve, check"],
        [str(10 * k) for k in range(10)],  # numeric ticks
    ],
)
def test_figure_labels_legends_keys_stay_in_figure(texts: list[str]) -> None:
    paras, rest = split_figure_text(_stack(texts))
    assert paras == [] and [ln.text for _, ln in rest] == texts


def test_figure_sentence_paragraph_is_released() -> None:
    """The real manual's p16 paragraph printed inside the bearing chart (6 lines, ~3 words a
    line, numbers and units mixed in) is running text."""
    paras, rest = split_figure_text(_stack(PARA))
    assert len(paras) == 1 and [ln.text for _, ln in paras[0]] == PARA and rest == []


def test_is_running_text_thresholds() -> None:
    words = ["Having", "observed", "on", "gauge", "57", "P.S.I.=", "21,000", "ft.lb.", "and"]
    assert is_running_text(words, 3)  # 9 words, 3 lines, mean 3
    assert not is_running_text(words, 4)  # mean 2.25
    assert not is_running_text(words[:7], 2)  # < 8 words
    assert not is_running_text(words, 1)  # one line
    nums = ["12", "14", "16", "18", "20", "22", "a1", "b2", "Nut"]
    assert not is_running_text(nums, 3)  # < 40% alphabetic
