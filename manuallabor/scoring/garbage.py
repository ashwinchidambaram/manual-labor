"""garbage_ratio: token-shape rules G1-G3 plus fragmentation, no dictionary (design 2.7)."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from manuallabor.contracts.block import Signal
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.types import GARBAGE_FRAG_FREE, GARBAGE_FRAG_SLOPE, clamp01, truncate

_BULLET_LINE_RE: Final = re.compile(r"^[ \t]*[^\w\s][ \t]+", re.M)
LEAD_STRIP: Final = "([{\"'“‘«"
TRAIL_STRIP: Final = ".,;:!?)]}\"'”’»"
ALLOWED_INNER: Final = "-/.,·'’°%±+×:_#&()\""
_BAD_CATEGORIES: Final = frozenset({"Co", "Cn", "Cs", "Cc", "Cf"})
_OK_FORMAT: Final = frozenset({"­", "​", "‌", "‍"})
_IGNORED_LETTERS: Final = frozenset("µμΩωπ")
_CJK: Final = frozenset({"CJK", "HIRAGANA", "KATAKANA"})


def _core(tok: str) -> str:
    return tok.lstrip(LEAD_STRIP).rstrip(TRAIL_STRIP)


def _is_ps(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "PS"


def _g1(tok: str) -> bool:
    if "�" in tok or "(cid:" in tok:
        return True
    return any(unicodedata.category(c) in _BAD_CATEGORIES and c not in _OK_FORMAT for c in tok)


def _g2(core: str) -> bool:
    if not core or len(set(core)) == 1:
        return False
    odd = sum(1 for c in core if _is_ps(c) and c not in ALLOWED_INNER)
    if odd >= 2:
        return True
    if len(core) >= 3 and not any(c.isdigit() for c in core):
        return sum(1 for c in core if _is_ps(c)) >= 0.6 * len(core)
    return False


def _script(ch: str) -> str | None:
    if not unicodedata.category(ch).startswith("L") or ch in _IGNORED_LETTERS:
        return None
    name = unicodedata.name(ch, "")
    if not name:
        return "UNKNOWN"
    first = name.split(" ", 1)[0]
    return "CJK" if first in _CJK else first


def _g3(tok: str) -> bool:
    scripts = {s for s in (_script(c) for c in tok) if s is not None}
    return len(scripts) >= 2


def is_bad_token(tok: str) -> bool:
    return _g1(tok) or _g2(_core(tok)) or _g3(tok)


def garbage_ratio(raw_text: str, *, is_table: bool) -> Signal | None:
    text = _BULLET_LINE_RE.sub("", raw_text).replace("|", " ")
    toks = text.split()
    if not toks:
        return None
    bad = [t for t in toks if is_bad_token(t)]
    frag = 0.0
    if not is_table:
        singles = sum(1 for t in toks if len(c := _core(t)) == 1 and c.isalpha())
        frag = singles / len(toks)
    value = clamp01(
        1 - len(bad) / len(toks) - GARBAGE_FRAG_SLOPE * max(0.0, frag - GARBAGE_FRAG_FREE)
    )
    parts = [f"{len(bad)}/{len(toks)} tokens symbol soup"]
    if bad:
        parts[0] += f" ({bad[0][:20]!r})"
    if frag > GARBAGE_FRAG_FREE:
        parts.append(f"fragmentation {frag:.2f}")
    return Signal(
        name=SignalName.garbage_ratio,
        value=value,
        critical=False,
        detail=truncate("; ".join(parts)),
    )
