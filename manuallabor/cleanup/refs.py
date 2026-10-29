"""Figure numbers and figure references in text (design 5.1). Pure.

Not parsed in v1: Roman numerals and unlabeled numbers; ``Table 3`` and ``figure out`` never
match."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from manuallabor.cleanup.types import RANGE_MAX

_SEP_CHARS: Final = "-–—‑."
_RANGE_CHARS: Final = "-–—‑"
# a figure number: optional letter prefix (``A-1``), digits, optional chapter part, optional
# letter suffix (``3a``)
N: Final = r"(?:[A-Z][-–—‑.]?)?\d+(?:[-–—‑.]\d+)?[a-zA-Z]?"
CAPTION_NUM_RE: Final = re.compile(rf"^(?i:figure|fig\.?)\s*(?P<n>{N})(?=[\s.:)]|$)")
_REF_HEAD_RE: Final = re.compile(rf"\b(?P<kw>(?i:fig(?:ure)?s?))\.?\s+(?P<a>{N})(?!\w)")
_REF_TAIL_RE: Final = re.compile(
    rf"\s*(?P<sep>(?i:,\s*(?:and|or|&)|,|and|&|or|to|through)|–|—|-)\s*(?P<b>{N})(?!\w)"
)
_PARTS_RE: Final = re.compile(
    r"^(?P<p>[A-Z])?(?P<ps>-)?(?P<a>\d+)(?:-(?P<b>\d+))?(?P<s>[a-zA-Z])?$"
)
_RANGE_WORDS: Final = frozenset({"–", "—", "-", "to", "through"})


def normalize_number(n: str) -> str:
    """Separators ``–—‑.`` become ``-``, leading zeros are stripped per numeric part, a
    trailing letter is lowercased: ``2–01`` -> ``2-1``, ``3A`` -> ``3a``."""
    t = re.sub(f"[{re.escape(_SEP_CHARS)}]", "-", n)
    m = _PARTS_RE.match(t)
    if m is None:
        return t
    out = (m["p"] or "") + (m["ps"] or "") + str(int(m["a"]))
    if m["b"] is not None:
        out += f"-{int(m['b'])}"
    if m["s"] is not None:
        out += m["s"].lower()
    return out


def caption_number(caption: str | None) -> str | None:
    """The normalized figure number of a caption (``Figure 3.`` -> ``3``), or None."""
    if not caption:
        return None
    m = CAPTION_NUM_RE.match(caption.strip())
    return normalize_number(m["n"]) if m else None


def is_chaptered(numbers: list[str | None]) -> bool:
    return any(n is not None and "-" in n for n in numbers)


@dataclass(frozen=True)
class Ref:
    number: str  # normalized
    text: str  # the whole matched reference (``Figures 3 and 4``)
    start: int


def _plain_range(raw: str) -> tuple[int, int] | None:
    """``3–5`` written as one number: (3, 5) when both ends are plain integers."""
    m = re.fullmatch(rf"(\d+)[{_RANGE_CHARS}](\d+)", raw)
    return (int(m[1]), int(m[2])) if m else None


def _expand(a: int, b: int) -> list[str] | None:
    if 0 <= b - a <= RANGE_MAX:
        return [str(k) for k in range(a, b + 1)]
    return None


def find_refs(text: str, chaptered: bool) -> list[Ref]:
    """Every figure reference in text order, one Ref per referenced number. ``\\s+`` after the
    keyword includes a newline (``Figure\\n2``). In a non-chaptered document ``3–5`` and
    ``3 to 5`` are ranges; in a chaptered one ``2-1`` is one number."""
    out: list[Ref] = []
    pos = 0
    while True:
        m = _REF_HEAD_RE.search(text, pos)
        if m is None:
            return out
        items: list[tuple[str | None, str]] = [(None, m["a"])]
        end = m.end()
        while True:
            t = _REF_TAIL_RE.match(text, end)
            if t is None:
                break
            items.append((t["sep"].casefold(), t["b"]))
            end = t.end()
        whole = text[m.start() : end]
        nums: list[str] = []
        prev: str | None = None
        for sep, raw in items:
            span = None if chaptered else _plain_range(raw)
            expanded = _expand(*span) if span else None
            if expanded is not None:
                nums.extend(expanded)
                prev = expanded[-1]
                continue
            n = normalize_number(raw)
            if (
                sep in _RANGE_WORDS
                and not chaptered
                and prev is not None
                and prev.isdigit()
                and n.isdigit()
            ):
                rng = _expand(int(prev), int(n))
                if rng is not None:
                    nums.extend(rng[1:])
                    prev = n
                    continue
            nums.append(n)
            prev = n
        for n in dict.fromkeys(nums):
            out.append(Ref(n, whole, m.start()))
        pos = end
