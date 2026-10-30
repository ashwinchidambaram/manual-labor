"""Queue card fields (design 13 section 2.8.3): one test group per rule, all pure."""

from __future__ import annotations

from manuallabor.contracts.block import Block, OcrWord, Signal, TableCell, TableData
from manuallabor.contracts.enums import BlockType, SignalName
from manuallabor.scoring.ocr import ocr_signals
from manuallabor.state.card import (
    EXCERPT_MAX,
    card_excerpt,
    cut,
    section_titles,
    weakest_word,
)
from tests.conftest import make_block


def heading(text: str, *, n: int, page: int, ro: int, level: int = 1) -> Block:
    return make_block(
        text, n=n, page=page, reading_order=ro, type=BlockType.heading, heading_level=level
    )


def para(text: str = "Check the drive belt.", *, n: int, page: int, ro: int) -> Block:
    return make_block(text, n=n, page=page, reading_order=ro)


# -- section_title ------------------------------------------------------------------------------


def test_section_title_heading_lookup_across_pages() -> None:
    blocks = [
        heading("4. Cooling", n=1, page=1, ro=0),
        heading("4.1  Coolant\nService", n=2, page=1, ro=1, level=2),
        para(n=3, page=1, ro=2),
        para(n=1, page=2, ro=3),  # next page, no heading of its own
        heading("4.2 Draining", n=2, page=2, ro=4, level=2),
        para(n=3, page=2, ro=5),
    ]
    t = section_titles(reversed(blocks))  # input order does not matter: reading order does
    assert t["b-doc-p001-01"] is None
    assert t["b-doc-p001-02"] == "4. Cooling"  # a heading takes the heading above it
    assert t["b-doc-p001-03"] == "4.1 Coolant Service"  # whitespace-normalised
    assert t["b-doc-p002-01"] == "4.1 Coolant Service"
    assert t["b-doc-p002-03"] == "4.2 Draining"
    assert t == section_titles(blocks)


def test_section_title_uses_clean_text_and_skips_empty_headings() -> None:
    blocks = [
        make_block(
            "Coolant Servise",
            n=1,
            reading_order=0,
            type=BlockType.heading,
            heading_level=1,
            clean_text="Coolant Service",
        ),
        make_block("  ", n=2, reading_order=1, type=BlockType.heading, heading_level=2),
        para(n=3, page=1, ro=2),
    ]
    assert section_titles(blocks)["b-doc-p001-03"] == "Coolant Service"


def test_section_title_none_without_heading() -> None:
    blocks = [para(n=1, page=1, ro=0), para(n=1, page=2, ro=1)]
    assert section_titles(blocks) == {"b-doc-p001-01": None, "b-doc-p002-01": None}
    # a block before the first heading has none either
    late = [para(n=1, page=1, ro=0), heading("1. Safety", n=2, page=1, ro=1)]
    assert section_titles(late)["b-doc-p001-01"] is None


# -- excerpt ------------------------------------------------------------------------------------


def test_excerpt_text_is_cut_at_a_word_boundary() -> None:
    raw = (
        "Do not operate the unit while the cover plate is removed.\n"
        "Disconnect the 12 V supply   and wait for the fan to stop before servicing."
    )
    ex = card_excerpt(make_block(raw))
    assert len(ex) <= EXCERPT_MAX and ex.endswith("…")
    assert "\n" not in ex and "  " not in ex
    body = ex[:-1]
    norm = " ".join(raw.split())
    assert norm.startswith(body) and norm[len(body)] == " "  # whole words only
    assert ex == "Do not operate the unit while the cover plate is removed. Disconnect the 12 V…"


def test_excerpt_prefers_clean_text_and_keeps_short_text() -> None:
    b = make_block("Chek the belt.", clean_text="Check the  belt.\n")
    assert card_excerpt(b) == "Check the belt."
    assert card_excerpt(make_block("Check the belt.")) == "Check the belt."


def test_excerpt_hard_cut_when_one_word_fills_the_limit() -> None:
    ex = cut("x" * 200)
    assert ex == "x" * (EXCERPT_MAX - 1) + "…"
    assert len(cut("word " * 40, 20)) <= 20


def test_excerpt_table_first_row_cells() -> None:
    cells = [
        TableCell(row=0, col=0, text="Part", is_header=True),
        TableCell(row=0, col=1, text="Torque\n(N·m)", is_header=True),
        TableCell(row=0, col=2, text=" ", is_header=True),
        TableCell(row=1, col=0, text="M8 bolt"),
        TableCell(row=1, col=1, text="25"),
    ]
    table = TableData(n_rows=2, n_cols=3, cells=cells, markdown="| Part | Torque |")
    b = make_block("Part Torque M8 bolt 25", type=BlockType.table, table=table)
    assert card_excerpt(b) == "Part · Torque (N·m)"
    # no table data: falls back to the text
    assert card_excerpt(make_block("Part Torque", type=BlockType.table)) == "Part Torque"


def test_excerpt_figure_caption_or_page() -> None:
    fig = make_block(
        "", page=3, type=BlockType.figure, figure_id="FIG-doc-p003-01", source="pymupdf", texts={}
    )
    assert card_excerpt(fig, "Figure 5.\nPressure valve exploded view.") == (
        "Figure 5. Pressure valve exploded view."
    )
    assert card_excerpt(fig, None) == "Figure on page 3"
    assert card_excerpt(fig, "   ") == "Figure on page 3"
    assert len(card_excerpt(fig, "Figure 9. " + "long caption " * 20)) <= EXCERPT_MAX


# -- weakest_word -------------------------------------------------------------------------------


def _ocr_block(words: list[tuple[str, float]], **kw: object) -> Block:
    text = " ".join(w for w, _ in words)
    b = make_block(
        text,
        source="ocr",
        texts={"ocr": text, "ocr_alt": text},
        ocr_words=[OcrWord(text=w, confidence=c) for w, c in words],
    )
    return b.model_copy(update={"signals": ocr_signals(b, numeric=False), **kw})


def test_weakest_word_reuses_the_ocr_detail() -> None:
    b = _ocr_block([("Drive", 0.99), ("belt,", 0.97), ("P/N", 0.95), ("4471-A", 0.899)])
    (sig,) = [s for s in b.signals if s.name == SignalName.ocr_min]
    assert sig.detail == "min 0.899 at '4471-A'; 4 words"
    assert weakest_word(b) == "4471-A"
    # a word with a quote is recorded with repr's double quotes and still read back exactly
    q = _ocr_block([("operator's", 0.5), ("manual", 0.9)])
    assert weakest_word(q) == "operator's"


def test_weakest_word_ocr_wins_over_disagreement() -> None:
    b = _ocr_block([("Set", 0.99), ("0.25", 0.6)])
    texts = {"ocr": "Set 0.25", "ocr_alt": "Sat 0.25"}
    agree = Signal(name=SignalName.parser_agreement, value=0.5, critical=True, detail="x")
    b = b.model_copy(update={"raw_text_by_parser": texts, "signals": [*b.signals, agree]})
    assert weakest_word(b) == "0.25"


def test_weakest_word_missing_ocr_and_agreeing_parsers_is_none() -> None:
    assert weakest_word(make_block("Check the belt.")) is None
    full = Signal(name=SignalName.parser_agreement, value=1.0, critical=False, detail="x")
    assert weakest_word(make_block("Check the belt.", signals=[full])) is None


def test_weakest_word_disagree_only() -> None:
    sig = Signal(
        name=SignalName.parser_agreement, value=0.8, critical=True, detail="pymupdf vs docling 0.8"
    )
    texts = {"pymupdf": "Set the gap to ±0.05 mm.", "docling": "Set the  GAP to +0.05 mm."}
    b = make_block(texts["pymupdf"], texts=texts, signals=[sig])
    # case and whitespace differences are not differences; the first real one is
    assert weakest_word(b) == "±0.05"
    # taken from the block's own reading
    d = make_block(texts["docling"], source="docling", texts=texts, signals=[sig])
    assert weakest_word(d) == "+0.05"
    # one reading runs out: the other reading's next word
    short = {"pymupdf": "Torque to 25", "docling": "Torque to 25 N·m"}
    assert weakest_word(make_block("Torque to 25", texts=short, signals=[sig])) == "N·m"
    # a single reader (no pair) has nothing to compare
    lone = make_block("Torque to 25", texts={"pymupdf": "Torque to 25"}, signals=[sig])
    assert weakest_word(lone) is None


def test_rules_are_deterministic() -> None:
    sig = Signal(name=SignalName.parser_agreement, value=0.8, critical=True, detail="x")
    texts = {"pymupdf": "A 1 b", "docling": "A 2 b"}
    blocks = [
        heading("1. Safety", n=1, page=1, ro=0),
        make_block("A 1 b", n=2, reading_order=1, texts=texts, signals=[sig]),
    ]
    first = (
        section_titles(blocks),
        [card_excerpt(b) for b in blocks],
        [weakest_word(b) for b in blocks],
    )
    for _ in range(3):
        assert first == (
            section_titles(blocks),
            [card_excerpt(b) for b in blocks],
            [weakest_word(b) for b in blocks],
        )
