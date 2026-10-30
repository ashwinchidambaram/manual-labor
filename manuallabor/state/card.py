"""Queue card fields (design 13 section 2.8.3, owner decision D4): deterministic, no model.

- ``section_title``: the text of the nearest heading block above the block in document reading
  order (headings on earlier pages count); ``None`` when no heading precedes it.
- ``excerpt``: the block's shown text (cleaned, else raw), whitespace-normalised and cut at a
  word boundary to at most ``EXCERPT_MAX`` characters with an ellipsis; a table shows its first
  row's cells joined by " · "; a figure shows its caption, else "Figure on page N".
- ``weakest_word``: the word the ``ocr_min`` signal recorded (parsed from its detail, never
  recomputed); else, when ``parser_agreement`` is below 1, the first word that differs between
  the two parser readings; else ``None``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from typing import Final

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType, SignalName
from manuallabor.scoring.agreement import PAIRS
from manuallabor.scoring.text import cmp_tokens, normalize_cmp

__all__ = [
    "EXCERPT_MAX",
    "WORD_MAX",
    "card_excerpt",
    "cut",
    "normalize_ws",
    "section_titles",
    "weakest_word",
]

EXCERPT_MAX: Final = 80
WORD_MAX: Final = 40  # the OCR detail already truncates its word to 40 characters
TABLE_SEP: Final = " · "
ELLIPSIS: Final = "…"
_WS_RE: Final = re.compile(r"\s+")
# scoring/ocr.py: f"min {conf:.3f} at {word!r}; {n} words"
_OCR_MIN_RE: Final = re.compile(r"^min [0-9.]+ at (?P<word>.+); \d+ words$", re.DOTALL)


def normalize_ws(s: str) -> str:
    """Every whitespace run (newlines included) becomes one space; ends stripped."""
    return _WS_RE.sub(" ", s).strip()


def cut(s: str, limit: int = EXCERPT_MAX) -> str:
    """``s`` whitespace-normalised; if longer than ``limit``, cut at the last word boundary
    that leaves room for the ellipsis (a hard cut when one word fills the room)."""
    s = normalize_ws(s)
    if len(s) <= limit:
        return s
    room = s[: limit - len(ELLIPSIS)]
    if s[len(room)] != " ":  # the cut falls inside a word: drop the partial word
        sp = room.rfind(" ")
        if sp > 0:
            room = room[:sp]
    return room.rstrip(" ,;:") + ELLIPSIS


def _shown(block: Block) -> str:
    return block.clean_text if block.clean_text is not None else block.raw_text


def _reading_key(b: Block) -> tuple[int, tuple[str, int, int]]:
    return (b.reading_order, ids.block_sort_key(b.id))


def section_titles(blocks: Iterable[Block]) -> dict[str, str | None]:
    """block id -> the nearest heading strictly above it in reading order (one document)."""
    out: dict[str, str | None] = {}
    current: str | None = None
    for b in sorted(blocks, key=_reading_key):
        out[b.id] = current
        if b.type == BlockType.heading:
            text = normalize_ws(_shown(b))
            if text:
                current = text
    return out


def _table_first_row(block: Block) -> str:
    if block.table is None:
        return ""
    cells = sorted((c for c in block.table.cells if c.row == 0), key=lambda c: c.col)
    return TABLE_SEP.join(t for t in (normalize_ws(c.text) for c in cells) if t)


def card_excerpt(block: Block, caption: str | None = None, limit: int = EXCERPT_MAX) -> str:
    if block.type == BlockType.figure:
        cap = normalize_ws(caption or "")
        return cut(cap, limit) if cap else f"Figure on page {block.page}"
    if block.type == BlockType.table:
        row = _table_first_row(block)
        if row:
            return cut(row, limit)
    return cut(_shown(block), limit)


def _ocr_word(detail: str | None) -> str | None:
    if not detail:
        return None
    m = _OCR_MIN_RE.match(detail)
    if m is None:
        return None
    try:
        word = ast.literal_eval(m.group("word"))
    except (ValueError, SyntaxError):
        return None
    if not isinstance(word, str):
        return None
    return normalize_ws(word) or None


def _first_difference(primary: str, other: str) -> str | None:
    """The first whitespace word whose comparison tokens differ between two readings, taken
    from ``primary`` (or from ``other`` once ``primary`` has run out)."""
    a = [w for w in normalize_cmp(primary).split() if cmp_tokens(w)]
    b = [w for w in normalize_cmp(other).split() if cmp_tokens(w)]
    for i in range(max(len(a), len(b))):
        wa = a[i] if i < len(a) else None
        wb = b[i] if i < len(b) else None
        if wa is None or wb is None or cmp_tokens(wa) != cmp_tokens(wb):
            word = wa if wa is not None else wb
            return cut(word, WORD_MAX) if word is not None else None
    return None


def _disagreement_word(block: Block) -> str | None:
    texts = block.raw_text_by_parser
    for a, b in PAIRS:  # the pair the parser_agreement scorer compared
        if a in texts and b in texts:
            if block.raw_source == b:
                a, b = b, a
            return _first_difference(texts[a], texts[b])
    return None


def weakest_word(block: Block) -> str | None:
    by_name = {s.name: s for s in block.signals}
    ocr = by_name.get(SignalName.ocr_min)
    if ocr is not None:
        word = _ocr_word(ocr.detail)
        if word is not None:
            return word
    agree = by_name.get(SignalName.parser_agreement)
    if agree is not None and agree.value < 1.0:
        return _disagreement_word(block)
    return None
