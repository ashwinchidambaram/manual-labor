"""Document lexicon for dehyphenation decisions (design 2, DH rules D3/D4). Pure."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from manuallabor.scoring.faithfulness import glyph_identity

# a line-end hyphen break between two letters: it attests neither "L-R" nor "LR"
BREAK_RE: Final = re.compile(r"(?<=[^\W\d_])-[ \t]*\r?\n[ \t]*(?=[^\W\d_])")
_WORD_RE: Final = re.compile(r"[^\W\d_]+")
_COMPOUND_RE: Final = re.compile(r"(?<![\w-])[^\W\d_]+(?:-[^\W\d_]+)+(?![\w])")


@dataclass(frozen=True)
class Lexicon:
    """Casefolded word counts and hyphen-compound pair counts (``self-contained``)."""

    words: Counter[str] = field(default_factory=Counter)
    compounds: Counter[str] = field(default_factory=Counter)

    def has_word(self, w: str) -> bool:
        return self.words[w.casefold()] > 0

    def has_compound(self, left: str, right: str) -> bool:
        return self.compounds[f"{left}-{right}".casefold()] > 0


def doc_lexicon(texts: Iterable[str]) -> Lexicon:
    """Lexicon over raw texts (in reading order). Each text gets the same glyph identity the
    unicode pass applies (ligatures, soft hyphens), and its line-end hyphen breaks are cut out
    first, so a break never attests its own join."""
    words: Counter[str] = Counter()
    compounds: Counter[str] = Counter()
    for raw in texts:
        t = BREAK_RE.sub(" ", glyph_identity(raw).text)
        for m in _WORD_RE.finditer(t):
            words[m.group().casefold()] += 1
        for m in _COMPOUND_RE.finditer(t):
            parts = m.group().casefold().split("-")
            for a, b in zip(parts, parts[1:], strict=False):
                compounds[f"{a}-{b}"] += 1
    return Lexicon(words, compounds)
