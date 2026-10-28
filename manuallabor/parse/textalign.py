"""Slice a coarse text onto a finer segmentation (design 01-parse section 8.2)."""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

_SNAP = 4


def _map_pos(opcodes: Sequence[tuple[str, int, int, int, int]], pos: int) -> int:
    """Map an offset in the joined parts (a) to an offset in the whole text (b)."""
    last_j = 0
    for tag, i1, i2, j1, j2 in opcodes:
        last_j = j2
        if pos > i2:
            continue
        if tag == "equal":
            return j1 + (pos - i1)
        if i2 == i1:
            return j1
        return j1 + int(round((pos - i1) / (i2 - i1) * (j2 - j1)))
    return last_j


def _snap(whole: str, cut: int, lo: int) -> int:
    """Move a cut onto the nearest whitespace boundary within a few characters."""
    n = len(whole)
    cut = max(lo, min(cut, n))

    def at_boundary(c: int) -> bool:
        if c <= 0 or c >= n:
            return True
        return whole[c - 1].isspace() or whole[c].isspace()

    if at_boundary(cut):
        return cut
    for d in range(1, _SNAP + 1):
        left = cut - d
        if left >= lo and at_boundary(left):
            return left
        right = cut + d
        if right <= n and at_boundary(right):
            return right
    return cut


def split_text_by_alignment(whole: str, parts: Sequence[str]) -> list[str]:
    """Return one slice of ``whole`` per entry of ``parts``.

    ``whole`` is aligned against the parts joined by a space; each part boundary is mapped through
    the matching blocks (unmatched stretches interpolate linearly). Slices are stripped and
    their concatenation equals ``whole`` modulo whitespace.
    """
    if not parts:
        return []
    if len(parts) == 1:
        return [whole.strip()]
    # Whitespace is normalized to single spaces (same length, so offsets carry over).
    joined = " ".join(parts)
    flat_whole = "".join(" " if ch.isspace() else ch for ch in whole)
    flat_joined = "".join(" " if ch.isspace() else ch for ch in joined)
    opcodes = SequenceMatcher(None, flat_joined, flat_whole, autojunk=False).get_opcodes()
    cuts: list[int] = []
    offset = 0
    prev = 0
    for part in parts[:-1]:
        offset += len(part)
        cut = _snap(whole, _map_pos(opcodes, offset), prev)
        cuts.append(cut)
        prev = cut
        offset += 1
    bounds = [0, *cuts, len(whole)]
    return [whole[bounds[i] : bounds[i + 1]].strip() for i in range(len(parts))]
