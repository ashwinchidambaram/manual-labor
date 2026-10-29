"""Comparison normalization N1-N6 and weighted token agreement (design 2.0).

Used by parser_agreement and textlayer_vs_ocr only; the faithfulness check never uses it."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final

from manuallabor.contracts._base import round6
from manuallabor.scoring.types import DIGIT_WEIGHT, MAX_NOTES, NUMERIC_PENALTY, NUMERIC_WINDOW

_DEHYPHEN_RE: Final = re.compile(r"([^\W\d_])-[ \t]*\n[ \t]*([^\W\d_])")
_BULLET_LINE_RE: Final = re.compile(r"^[ \t]*[^\w\s][ \t]+", re.M)
TOKW: Final = re.compile(r"\w+(?:[.,]\d+)*|[^\w\s|]")

# Text layer char -> what OCR is measured to read it as (text layer -> OCR direction only).
OCR_DEGRADE: Final[dict[str, str]] = {
    "·": "-.+•",
    "±": "+",
    "•": "*«¢eo+-.",
    "×": "xX",
    "°": "o\"'",
    "–": "-",
    "—": "-",
    "’": "'",
    "“": '"',
    "”": '"',
}

_LOOKALIKE_GROUPS: Final = (
    ("OoDQ", "0"),
    ("lIi|", "1"),
    ("Ss", "5"),
    ("B", "8"),
    ("Zz", "2"),
    ("Gb", "6"),
    ("gq", "9"),
    ("T", "7"),
    ("A", "4"),
)
LOOKALIKES: Final[frozenset[frozenset[str]]] = frozenset(
    frozenset((a, d)) for letters, d in _LOOKALIKE_GROUPS for a in letters
)


def _has_digit(t: str) -> bool:
    return any(c.isdigit() for c in t)


def normalize_cmp(s: str) -> str:
    """N1-N3 on a whole text."""
    s = unicodedata.normalize("NFKC", s).replace("­", "")
    s = _DEHYPHEN_RE.sub(r"\1\2", s)
    return _BULLET_LINE_RE.sub("", s)


def cmp_tokens(s: str) -> list[str]:
    """N1-N5: normalized comparison tokens."""
    return [t if _has_digit(t) else t.casefold() for t in TOKW.findall(normalize_cmp(s))]


def weight(t: str) -> int:
    return DIGIT_WEIGHT if _has_digit(t) else 1


def numeric_context(ts: list[str]) -> list[bool]:
    """N6: token i is in numeric context if a token within NUMERIC_WINDOW of it has a digit."""
    digit = [_has_digit(t) for t in ts]
    n = len(ts)
    return [
        any(digit[j] for j in range(max(0, i - NUMERIC_WINDOW), min(n, i + NUMERIC_WINDOW + 1)))
        for i in range(n)
    ]


@dataclass(frozen=True)
class Agreement:
    value: float
    k_numeric: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def _degrades(a: str, b: str) -> bool:
    """b is a char-by-char OCR degradation of a (text layer a -> OCR b)."""
    if len(a) != len(b):
        return False
    return all(y == x or y in OCR_DEGRADE.get(x, "") for x, y in zip(a, b, strict=True))


def _confusable(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b) or not a:
        return False
    any_digit = False
    for x, y in zip(a, b, strict=True):
        if len(x) != len(y):
            return False
        for xc, yc in zip(x, y, strict=True):
            if xc != yc and frozenset((xc, yc)) not in LOOKALIKES:
                return False
        any_digit = any_digit or _has_digit(x) or _has_digit(y)
    return any_digit and a != b


def weighted_agreement(a: list[str], b: list[str], *, directional: bool) -> Agreement:
    """Digit-weighted token agreement between two token lists (design 2.0 steps 1-7)."""
    wa = math.fsum(weight(t) for t in a)
    wb = math.fsum(weight(t) for t in b)
    if wa + wb == 0:
        return Agreement(1.0)
    ctx_a, ctx_b = numeric_context(a), numeric_context(b)
    matched: list[float] = []
    k_numeric = 0
    notes: list[str] = []
    ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        sa, sb = a[i1:i2], b[j1:j2]
        w_a = math.fsum(weight(t) for t in sa)
        w_b = math.fsum(weight(t) for t in sb)
        if tag == "equal":
            matched.append(w_a)
            continue
        ja, jb = "".join(sa).casefold(), "".join(sb).casefold()
        if tag == "replace" and ja == jb:
            matched.append((w_a + w_b) / 2.0)  # spacing only: 10A / 10 A, witha / with a
            continue
        if tag == "replace" and directional and _degrades(ja, jb):
            matched.append((w_a + w_b) / 2.0)  # measured OCR degradation of the text layer
            continue
        if any(ctx_a[i1:i2]) or any(ctx_b[j1:j2]):
            k_numeric += 1
        if len(notes) < MAX_NOTES:
            pa, pb = " ".join(sa), " ".join(sb)
            prefix = "confusable " if _confusable(sa, sb) else ""
            notes.append(f"{prefix}'{pa}' vs '{pb}'")
    ratio = 2.0 * math.fsum(matched) / (wa + wb)
    value = min(ratio, NUMERIC_PENALTY**k_numeric)
    return Agreement(round6(min(1.0, max(0.0, value))), k_numeric, tuple(notes))
