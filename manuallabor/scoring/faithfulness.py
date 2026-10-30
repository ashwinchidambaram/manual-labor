"""Deterministic faithfulness check: clean_text may differ from raw_text only by the allowed
edits AE1-AE7 (design 4). Pure functions; no model output is trusted here."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from manuallabor.contracts._base import round6
from manuallabor.contracts.block import (
    DiffOp,
    FaithfulnessResult,
    FaithfulnessViolation,
    NumericVariant,
    TableData,
)
from manuallabor.contracts.enums import BlockType, DiffOpKind, FaithViolationKind
from manuallabor.parse.text import TOKEN_RE, collapse_ws, hf_key
from manuallabor.scoring.layout import lis_keep
from manuallabor.scoring.numeric import FAITH_NUM_RE
from manuallabor.scoring.types import (
    FAITH_MAX_CHARS,
    FAITH_REWRITE_QUICK_RATIO,
    REORDER_MAX_STEPS,
    REORDER_MAX_UNITS,
    ReorderEvidence,
)

LIGATURES: Final = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
SPACE_LIKE: Final = frozenset([" ", " "] + [chr(c) for c in range(0x2000, 0x200B)])  # U+2000-U+200A
SOFT_HYPHEN: Final = "­"
BULLETS: Final = "•·◦▪‣●*–-"
LIST_OCR_BULLETS: Final = "¢+o«"
CANON_BULLET: Final = "•"
# glyphs that also read as a sign: before a number (``+ 5 V``, ``- 12 V``, ``– 40 °C``) they
# are part of the value, never a bullet (AE4)
SIGN_GLYPHS: Final = "+-–"


def sign_before_number(glyph: str, rest: str) -> bool:
    """``glyph`` + ``rest`` (the text after the glyph on its line) is a signed number."""
    return glyph in SIGN_GLYPHS and rest.lstrip(" \t")[:1].isdigit()


_AE2_RE: Final = re.compile(r"(?<=[^\W\d_])-[ \t]*\n[ \t]*(?=[^\W\d_])")
_AE2_LINE_END_RE: Final = re.compile(r"[^\W\d_]-[ \t]*$")
_LOOSE_RE: Final = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")
_SENTENCE_SPLIT_RE: Final = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][)\"”’]))\s(?=[A-Z0-9•(])")
_GFM_SEP_RE: Final = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


# ---------------------------------------------------------------------------------------------
# MappedText


@dataclass(frozen=True)
class MappedText:
    """Canonical text with, for every char, its index in the original string."""

    text: str
    src: tuple[int, ...]
    optional: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if len(self.text) != len(self.src):
            raise ValueError("MappedText: text and src lengths differ")

    def __len__(self) -> int:
        return len(self.text)

    def slice(self, i: int, j: int) -> MappedText:
        return MappedText(
            self.text[i:j],
            self.src[i:j],
            frozenset(k - i for k in self.optional if i <= k < j),
        )

    @staticmethod
    def identity(s: str) -> MappedText:
        return MappedText(s, tuple(range(len(s))))


class _Builder:
    def __init__(self) -> None:
        self.chars: list[str] = []
        self.src: list[int] = []
        self.opt: list[int] = []

    def add(self, ch: str, src: int, optional: bool = False) -> None:
        if optional:
            self.opt.append(len(self.chars))
        self.chars.append(ch)
        self.src.append(src)

    def extend(self, mt: MappedText) -> None:
        base = len(self.chars)
        self.chars.extend(mt.text)
        self.src.extend(mt.src)
        self.opt.extend(base + k for k in sorted(mt.optional))

    def build(self) -> MappedText:
        return MappedText("".join(self.chars), tuple(self.src), frozenset(self.opt))


def concat(
    parts: Sequence[MappedText], sep: str = " ", sep_src: Sequence[int] | None = None
) -> MappedText:
    b = _Builder()
    for n, p in enumerate(parts):
        if n:
            s = sep_src[n - 1] if sep_src is not None else (p.src[0] if p.src else 0)
            for ch in sep:
                b.add(ch, s)
        b.extend(p)
    return b.build()


# ---------------------------------------------------------------------------------------------
# canonicalization steps (each MappedText -> MappedText, src always into the original string)


def glyph_identity(s: str) -> MappedText:
    """AE5: NFC per combining sequence, ligatures to letters, soft hyphen deleted,
    NBSP-like spaces to ' '; CRLF and lone CR become LF (before dehyphenation and alignment)."""
    b = _Builder()
    i, n = 0, len(s)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(s[j]):
            j += 1
        seg = s[i:j]
        if j == i + 1:
            ch = seg
            if ch == "\r":
                if i + 1 >= n or s[i + 1] != "\n":
                    b.add("\n", i)  # lone CR is a line break; CR of CRLF is dropped
            elif ch == SOFT_HYPHEN:
                pass
            elif ch in SPACE_LIKE:
                b.add(" ", i)
            elif ch in LIGATURES:
                for c in LIGATURES[ch]:
                    b.add(c, i)
            else:
                b.add(ch, i)
        else:
            norm = unicodedata.normalize("NFC", seg)
            if norm == seg:
                for k, c in enumerate(seg):
                    b.add(c, i + k)
            else:
                for c in norm:
                    b.add(c, i)
        i = j
    return b.build()


def _lines(mt: MappedText) -> list[tuple[int, int]]:
    """(start, end) of each line, end excludes the newline."""
    out: list[tuple[int, int]] = []
    start = 0
    for k, ch in enumerate(mt.text):
        if ch == "\n":
            out.append((start, k))
            start = k + 1
    out.append((start, len(mt.text)))
    return out


_DIGIT_RUN_RE: Final = re.compile(r"\d+")


def _num_eq(a: str, b: str) -> bool:
    return (a.lstrip("0") or "0") == (b.lstrip("0") or "0")


@dataclass(frozen=True)
class HfGroup:
    """Recorded header/footer strings with one digit template (``hf_key``).

    ``page_slots``: indices of the digit runs that carry the page number (the ``{n}`` slot);
    ``fixed``: index -> the value every member has (a run that never varies)."""

    members: tuple[str, ...]
    page_slots: frozenset[int]
    fixed: Mapping[int, str]
    pages: Mapping[str, frozenset[int]]  # member -> pages it was recorded on ({} if unknown)
    with_pages: bool


@dataclass(frozen=True)
class HfTables:
    """Recorded header/footer strings that contain a letter (a bare number is never treated as
    a header/footer: deleting it could delete a value), grouped by digit template."""

    exact: frozenset[str]
    groups: Mapping[str, HfGroup]


def _group(members: Sequence[str], pages: Mapping[str, frozenset[int]] | None) -> HfGroup:
    runs = {m: _DIGIT_RUN_RE.findall(m) for m in members}
    n = len(runs[members[0]])
    slots: set[int] = set()
    if pages is not None:
        # the {n} slot: the run that equals the recording page on every recorded occurrence
        pairs = [(m, p) for m in members for p in sorted(pages.get(m, ()))]
        if pairs:
            slots = {k for k in range(n) if all(_num_eq(runs[m][k], str(p)) for m, p in pairs)}
    else:
        # no page record: the single run that varies across the recorded strings
        varying = {k for k in range(n) if len({runs[m][k] for m in members}) > 1}
        if len(varying) == 1:
            slots = varying
    fixed = {
        k: runs[members[0]][k]
        for k in range(n)
        if k not in slots and len({runs[m][k] for m in members}) == 1
    }
    return HfGroup(
        tuple(members),
        frozenset(slots),
        fixed,
        dict(pages or {}),
        pages is not None,
    )


def hf_tables(
    hf_strings: Iterable[str], hf_pages: Mapping[str, Iterable[int]] | None = None
) -> HfTables:
    """``hf_pages`` (recorded string -> the pages it was recorded on) supersedes
    ``hf_strings`` when given: it identifies the page slot and the doc-wide constants."""
    pages: dict[str, frozenset[int]] | None = None
    if hf_pages is not None:
        pages = {}
        for h, ps in hf_pages.items():
            c = collapse_ws(h)
            pages[c] = pages.get(c, frozenset()) | frozenset(ps)
        source: Iterable[str] = pages
    else:
        source = hf_strings
    usable = sorted({collapse_ws(h) for h in source if any(c.isalpha() for c in h)})
    by_key: dict[str, list[str]] = {}
    for h in usable:
        by_key.setdefault(hf_key(h), []).append(h)
    groups = {
        k: _group(v, None if pages is None else {m: pages[m] for m in v}) for k, v in by_key.items()
    }
    return HfTables(frozenset(usable), groups)


def is_hf_line(line: str, tables: HfTables, page: int | None) -> bool:
    """AE3 (design 4.1): a raw line may be removed as a header/footer only if
    (a) it is the string recorded on THIS page (page record known), or
    (b) it has the digit template of a recorded group, every run outside the group's page slot
        (``{n}``) equals the value all recorded strings share there, and the page slot equals
        this block's page (``Page {n} of 60``: n == page and 60 stays 60), or
    (c) the group has no page slot and the line is its one recorded string, a doc-wide
        constant (recorded on >= 2 pages when the page record is known).
    Any other line, in particular one carrying another numeric token or another page's
    footer, is body text: deleting it is a ``deletion`` violation."""
    c = collapse_ws(line)
    if not c or not any(ch.isalpha() for ch in c):
        return False
    grp = tables.groups.get(hf_key(c))
    if grp is None:
        return False
    same = [m for m in grp.members if m.casefold() == c.casefold()]
    if grp.with_pages and page is not None and any(page in grp.pages[m] for m in same):
        return True  # (a)
    nums = _DIGIT_RUN_RE.findall(c)
    if any(k not in grp.page_slots and k not in grp.fixed for k in range(len(nums))):
        return False  # a run that varies across recorded strings but is not the page
    if any(nums[k] != v for k, v in grp.fixed.items()):
        return False
    if grp.page_slots:  # (b)
        return page is not None and all(_num_eq(nums[k], str(page)) for k in grp.page_slots)
    # (c): no page slot and every run fixed: c is the group's recorded string (case aside)
    if not same:
        return False
    return not grp.with_pages or len(frozenset().union(*(grp.pages[m] for m in same))) >= 2


def hf_edge_lines(lines: Sequence[str], tables: HfTables, page: int | None) -> frozenset[int]:
    """AE3 position rule: the indices of the lines that may be removed as a header/footer.
    Only a leading or trailing remnant qualifies: the run of ``is_hf_line`` lines that starts
    at the first non-blank line, and the run that ends at the last one (a two-line running
    footer ``Acme X200 Service Manual`` + ``Page 3``). A recorded string with body text on both
    sides is body text (``Refer to the\nAcme X200 Service Manual\nbefore you start.``). A block
    is never emptied: when every non-blank line would go (a paragraph that is only
    ``Page 3``), nothing is removed. Blank lines inside a run are skipped over."""
    if not tables.exact:
        return frozenset()
    body = [k for k, ln in enumerate(lines) if collapse_ws(ln)]
    out: set[int] = set()
    for order in (body, body[::-1]):
        for k in order:
            if not is_hf_line(lines[k], tables, page):
                break
            out.add(k)
    return frozenset() if len(out) == len(body) else frozenset(out)


def _delete_ranges(mt: MappedText, ranges: list[tuple[int, int]]) -> MappedText:
    if not ranges:
        return mt
    drop = [False] * len(mt.text)
    for a, z in ranges:
        for k in range(a, z):
            drop[k] = True
    b = _Builder()
    for k, ch in enumerate(mt.text):
        if not drop[k]:
            b.add(ch, mt.src[k], k in mt.optional)
    return b.build()


def _line_delete_range(mt: MappedText, a: int, z: int) -> tuple[int, int]:
    """A whole line plus one adjacent newline."""
    if z < len(mt.text):
        return a, z + 1
    if a > 0:
        return a - 1, z
    return a, z


@dataclass(frozen=True)
class HfDeleted:
    text: str  # collapse_ws of the deleted raw line
    rel_pos: float  # its start / len(raw), to place inline clean occurrences


def strip_hf_raw(
    mt: MappedText,
    hf_strings: Sequence[str],
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> tuple[MappedText, list[HfDeleted]]:
    """AE3 on raw: delete the whole lines that are a known header/footer (``is_hf_line``) at
    the block's edges (``hf_edge_lines``)."""
    tables = hf_tables(hf_strings, hf_pages)
    if not tables.exact:
        return mt, []
    ranges: list[tuple[int, int]] = []
    deleted: list[HfDeleted] = []
    total = max(1, len(mt.text))
    spans = _lines(mt)
    for k in sorted(hf_edge_lines([mt.text[a:z] for a, z in spans], tables, page)):
        a, z = spans[k]
        ranges.append(_line_delete_range(mt, a, z))
        deleted.append(HfDeleted(collapse_ws(mt.text[a:z]), a / total))
    return _delete_ranges(mt, _merge(ranges)), deleted


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, z in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], z))
        else:
            out.append((a, z))
    return out


def _inline_pattern(text: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\S)" + r"\s+".join(re.escape(t) for t in text.split()) + r"(?!\S)")


def strip_hf_clean(mt: MappedText, deleted: Sequence[HfDeleted], raw_rest: str) -> MappedText:
    """AE3 on clean: remove what raw's deleted header/footer lines became. A deleted string is
    removed only as a surplus occurrence: at most as many times as raw had it deleted, and
    only as many times as clean has it more often than what raw kept (``raw_rest``), so an
    interior copy that raw keeps can never be dropped from clean. The occurrences nearest to
    the raw line's relative position are taken (a whole line, or inline when the cleanup
    joined it into its neighbours); the whitespace left behind is collapsed by AE1."""
    if not deleted:
        return mt
    remaining = Counter(d.text for d in deleted)
    total = max(1, len(mt.text))
    spans: list[tuple[int, int]] = []
    for text in sorted(remaining):
        rx = _inline_pattern(text)
        occ = [m.span() for m in rx.finditer(mt.text)]
        surplus = len(occ) - len(rx.findall(raw_rest))
        positions = sorted(d.rel_pos for d in deleted if d.text == text)
        take = min(remaining[text], max(0, surplus))
        chosen: set[int] = set()
        for rel in positions[:take]:
            cands = [k for k in range(len(occ)) if k not in chosen]
            if not cands:
                break
            best = min(cands, key=lambda k: (abs(occ[k][0] / total - rel), k))
            chosen.add(best)
        spans.extend(occ[k] for k in sorted(chosen))
    return _delete_ranges(mt, _merge(spans))


def normalize_bullets(mt: MappedText, block_type: BlockType) -> MappedText:
    """AE4: a line-start bullet glyph followed by whitespace (or the end of the text) becomes the
    canonical bullet, unless it is the sign of a number (``+ 5 V``, ``- 12 V``). "Whitespace"
    is the same notion AE1 collapses, so that canonicalization is idempotent (a glyph alone on
    its line is a line-start glyph again after the collapse)."""
    glyphs = BULLETS + (LIST_OCR_BULLETS if block_type == BlockType.list else "")
    chars = list(mt.text)
    n = len(chars)
    for a, z in _lines(mt):
        k = a
        while k < z and chars[k].isspace():
            k += 1
        if (
            k < z
            and chars[k] in glyphs
            and (k + 1 == n or chars[k + 1].isspace())
            and not sign_before_number(chars[k], mt.text[k + 1 : z])
        ):
            chars[k] = CANON_BULLET
    return MappedText("".join(chars), mt.src, mt.optional)


def dehyphenate(mt: MappedText) -> MappedText:
    """AE2: join `letter-\\n letter`, keep the hyphen and mark it optional."""
    matches = list(_AE2_RE.finditer(mt.text))
    if not matches:
        return mt
    b = _Builder()
    pos = 0
    for m in matches:
        for k in range(pos, m.start()):
            b.add(mt.text[k], mt.src[k], k in mt.optional)
        b.add("-", mt.src[m.start()], True)
        pos = m.end()
    for k in range(pos, len(mt.text)):
        b.add(mt.text[k], mt.src[k], k in mt.optional)
    return b.build()


def collapse(mt: MappedText) -> MappedText:
    """AE1: every whitespace run becomes one ' '; both ends stripped."""
    b = _Builder()
    in_ws = False
    for k, ch in enumerate(mt.text):
        if ch.isspace():
            if not in_ws:
                b.add(" ", mt.src[k])
            in_ws = True
        else:
            b.add(ch, mt.src[k], k in mt.optional)
            in_ws = False
    out = b.build()
    i, j = 0, len(out.text)
    while i < j and out.text[i] == " ":
        i += 1
    while j > i and out.text[j - 1] == " ":
        j -= 1
    return out.slice(i, j) if (i, j) != (0, len(out.text)) else out


@dataclass(frozen=True)
class Canon:
    mt: MappedText
    hf_deleted: tuple[HfDeleted, ...]
    pre_ae2: MappedText  # after AE5, AE3, AE4 (line structure kept): used for line units


def canonicalize(
    s: str,
    *,
    hf_strings: Sequence[str] = (),
    block_type: BlockType = BlockType.paragraph,
    raw_deleted: Sequence[HfDeleted] | None = None,
    raw_rest: str = "",
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> Canon:
    """Steps 1-5 of design 4.2. With raw_deleted=None this is the raw side (AE3 deletes known
    header/footer lines); otherwise the clean side (AE3 removes what raw deleted)."""
    mt = glyph_identity(s)
    deleted: list[HfDeleted] = []
    if raw_deleted is None:
        mt, deleted = strip_hf_raw(mt, hf_strings, page, hf_pages)
    else:
        mt = strip_hf_clean(mt, raw_deleted, raw_rest)
    mt = normalize_bullets(mt, block_type)
    pre = mt
    mt = collapse(dehyphenate(mt))
    return Canon(mt, tuple(deleted), pre)


# ---------------------------------------------------------------------------------------------
# tables (AE6)


def _cell_canon(text: str, offset: int) -> MappedText:
    mt = collapse(glyph_identity(text))
    return MappedText(mt.text, tuple(offset + s for s in mt.src), frozenset())


def _clampf(n: int) -> int:
    return max(0, n - 1)


def table_raw_canon(table: TableData, raw: str) -> MappedText:
    """The table grid in row order: cells ' | ', rows '\\n', covered span slots ''."""
    origin = {(c.row, c.col): c for c in table.cells}
    cap = _clampf(len(raw))
    b = _Builder()
    cursor = 0
    for r in range(table.n_rows):
        row_start = min(cursor, cap)
        if r:
            b.add("\n", row_start)
        for c in range(table.n_cols):
            if c:
                for ch in " | ":
                    b.add(ch, min(cursor, cap))
            cell = origin.get((r, c))
            if cell is None:
                continue
            t = cell.text.strip()
            k = raw.find(t, cursor) if t else -1
            if k >= 0:
                lead = len(cell.text) - len(cell.text.lstrip())
                inner = _cell_canon(cell.text, k - lead)
                b.extend(MappedText(inner.text, tuple(min(max(0, s), cap) for s in inner.src)))
                cursor = k + len(t)
            else:
                inner = _cell_canon(cell.text, 0)
                b.extend(MappedText(inner.text, tuple(row_start for _ in inner.src)))
    return b.build()


def _split_gfm_row(line: str, offset: int) -> list[tuple[str, int]]:
    """Cells of one GFM row as (unescaped text, start offset); outer pipes dropped."""
    cells: list[tuple[str, int]] = []
    buf: list[str] = []
    start = offset
    k = 0
    while k < len(line):
        ch = line[k]
        if ch == "\\" and k + 1 < len(line) and line[k + 1] == "|":
            buf.append("|")
            k += 2
            continue
        if ch == "|":
            cells.append(("".join(buf), start))
            buf = []
            start = offset + k + 1
        else:
            buf.append(ch)
        k += 1
    cells.append(("".join(buf), start))
    cells = cells[1:]  # text before the leading pipe
    closed = line.rstrip().endswith("|") and not line.rstrip().endswith("\\|")
    if closed and cells and not cells[-1][0].strip():
        cells = cells[:-1]
    return cells


def parse_gfm(clean: str) -> list[list[tuple[str, int]]] | None:
    """Rows of a GFM table (separator dropped), or None if clean is not one."""
    lines: list[tuple[str, int]] = []
    pos = 0
    for raw_line in clean.split("\n"):
        if raw_line.strip():
            lines.append((raw_line, pos))
        pos += len(raw_line) + 1
    if len(lines) < 2 or not all(t.lstrip().startswith("|") for t, _ in lines):
        return None
    if not _GFM_SEP_RE.match(lines[1][0].strip()):
        return None
    return [_split_gfm_row(t, off) for n, (t, off) in enumerate(lines) if n != 1]


def table_clean_canon(rows: list[list[tuple[str, int]]], clean: str) -> MappedText:
    cap = _clampf(len(clean))
    b = _Builder()
    for r, row in enumerate(rows):
        row_off = row[0][1] if row else 0
        if r:
            b.add("\n", min(row_off, cap))
        for c, (text, off) in enumerate(row):
            if c:
                for ch in " | ":
                    b.add(ch, min(max(0, off - 1), cap))
            inner = _cell_canon(text, off)
            b.extend(MappedText(inner.text, tuple(min(s, cap) for s in inner.src)))
    return b.build()


def table_token(s: str) -> str:
    """One token for the table/raw coverage comparison: AE5 glyph identity (``TOKEN_RE`` has
    already split on whitespace, ``|`` and the canonical bullet)."""
    return glyph_identity(s).text


def raw_table_rows(raw: str) -> int | None:
    """The number of rows of raw_text when they are detectable: raw is in the row convention
    (``table_raw_text``: cells joined `` | ``, one row per line), so every non-blank line is
    one row. None when no line carries a cell separator (plain extracted text, where a wrapped
    cell can span lines)."""
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    return len(lines) if any(" | " in ln for ln in lines) else None


@dataclass(frozen=True)
class TableCoverage:
    missing: Counter[str]  # raw tokens the cells lack
    extra: Counter[str]  # cell tokens raw lacks
    raw_rows: int | None  # None: not detectable
    cell_rows: int  # rows with at least one non-empty cell

    @property
    def ok(self) -> bool:
        rows_ok = self.raw_rows is None or self.raw_rows == self.cell_rows
        return not self.missing and not self.extra and rows_ok

    def detail(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"{sum(self.missing.values())} raw tokens missing from the cells")
        if self.extra:
            parts.append(f"{sum(self.extra.values())} cell tokens not in raw")
        if self.raw_rows is not None and self.raw_rows != self.cell_rows:
            parts.append(f"{self.cell_rows} rows vs {self.raw_rows} raw rows")
        return "; ".join(parts) or "cells cover raw"


def table_coverage(raw: str, rows: Sequence[Sequence[str]]) -> TableCoverage:
    """AE6 coverage (design 4.3): the multiset of non-empty cell tokens must equal the token
    multiset of raw_text, and the number of non-empty rows must equal the raw row count when
    it is detectable. The structured table can come from another parser than raw_text and
    miss a row that raw has; the grid-to-grid comparison alone cannot see that."""
    rc = Counter(t for m in TOKEN_RE.finditer(raw) if (t := table_token(m.group())))
    cc = Counter(
        t
        for row in rows
        for cell in row
        for m in TOKEN_RE.finditer(cell)
        if (t := table_token(m.group()))
    )
    n_rows = sum(1 for row in rows if any(cell.strip() for cell in row))
    return TableCoverage(rc - cc, cc - rc, raw_table_rows(raw), n_rows)


def table_coverage_violations(
    raw: str, clean: str, rows: Sequence[Sequence[tuple[str, int]]]
) -> list[FaithfulnessViolation]:
    """``table_coverage`` as violations: a raw token missing from the cells is a ``deletion``
    (its surplus raw occurrences), a cell token raw lacks an ``insertion``; a row count that
    differs from the detectable raw rows is one ``deletion`` (fewer rows: raw rows merged or
    dropped) or ``insertion`` over the whole text."""
    cov = table_coverage(raw, [[text for text, _ in row] for row in rows])
    if cov.ok:
        return []
    out: list[FaithfulnessViolation] = []
    if cov.missing:
        occ: dict[str, list[tuple[int, int]]] = {}
        for m in TOKEN_RE.finditer(raw):
            t = table_token(m.group())
            if t in cov.missing:
                occ.setdefault(t, []).append(m.span())
        for t in sorted(occ):
            for span in occ[t][len(occ[t]) - cov.missing[t] :]:
                out.append(_violation(FaithViolationKind.deletion, raw, clean, span, None))
    if cov.extra:
        cap = len(clean)
        cocc: dict[str, list[tuple[int, int]]] = {}
        for row in rows:
            for text, off in row:
                for m in TOKEN_RE.finditer(text):
                    t = table_token(m.group())
                    if t in cov.extra:
                        a, z = min(off + m.start(), cap), min(off + m.end(), cap)
                        cocc.setdefault(t, []).append((a, z))
        for t in sorted(cocc):
            for span in cocc[t][len(cocc[t]) - cov.extra[t] :]:
                out.append(_violation(FaithViolationKind.insertion, raw, clean, None, span))
    if cov.raw_rows is not None and cov.raw_rows != cov.cell_rows:
        kind = (
            FaithViolationKind.deletion
            if cov.cell_rows < cov.raw_rows
            else FaithViolationKind.insertion
        )
        out.append(_violation(kind, raw, clean, (0, len(raw)), (0, len(clean))))
    return out


# ---------------------------------------------------------------------------------------------
# numeric variants


def _token_rx(tok: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)")


_CONFUSABLE_GROUPS: Final = ("0O", "1lI|", "5S", "8B", "2Z", "6G", "9g", ".,")
_CONFUSABLE_CLASS: Final = {ch: grp[0] for grp in _CONFUSABLE_GROUPS for ch in grp}
_TOKEN_PUNCT: Final = "\"'“”‘’()[]{}<>:;!?,."


def ocr_confusable(raw: str, chosen: str) -> bool:
    """``chosen`` is a plausible OCR/text-layer misreading of ``raw`` (a look-alike): the same
    length, and every character pair that differs lies inside one confusable group
    ``0O 1lI| 5S 8B 2Z 6G 9g .,``. ``35`` -> ``40`` is not a misreading, it is a new value.
    Adding or dropping a character (``35`` -> ``350``, ``35`` -> ``3``, ``1`` -> ``11``) is
    never a look-alike: such a change needs two independent attesters, not one."""
    if not raw or not chosen or raw == chosen or len(raw) != len(chosen):
        return False
    cls = _CONFUSABLE_CLASS
    return all(
        x == y or (x in cls and y in cls and cls[x] == cls[y])
        for x, y in zip(raw, chosen, strict=True)
    )


def _has_digit(tok: str) -> bool:
    return any(ch.isdigit() for ch in tok)


def numeric_tokens(text: str) -> list[str]:
    """The digit-bearing whitespace tokens of text (``TOKEN_RE``), in order: the tokens the
    numeric-variant rule and the agent's number attestation compare."""
    return [t for t in TOKEN_RE.findall(text) if _has_digit(t)]


def _numeric_index(spans: Sequence[tuple[int, int, bool]], offset: int) -> tuple[int, int]:
    """(how many digit-bearing tokens precede the token containing ``offset``, how many
    digit-bearing tokens the text has once that token reads as a number)."""
    total = sum(d for _, _, d in spans)
    n = 0
    for a, z, digit in spans:
        if a <= offset < z:
            return n, total + (not digit)
        if a > offset:
            return n, total + 1
        n += digit
    return n, total + 1


def _confirmed_at(at: tuple[int, int], src_numeric: Sequence[str], chosen: str) -> bool:
    """The other reading has as many digit-bearing tokens as raw and ``chosen`` is its i-th
    (exact index, no slack: a neighbouring number is a different value, and a reading with an
    extra or a missing number cannot be aligned by counting)."""
    i, total = at
    return len(src_numeric) == total and src_numeric[i].strip(_TOKEN_PUNCT) == chosen


def apply_variants(
    mt: MappedText,
    variants: Sequence[NumericVariant],
    sources: Mapping[str, str],
    raw_source: str,
    raw: str | None = None,
) -> tuple[MappedText, list[NumericVariant]]:
    """Replace each whole-token occurrence of a variant's raw that is *confirmed* (design 4.4
    step 1): ``chosen`` is an OCR-confusable reading of ``raw`` (``ocr_confusable``) and the
    source reading has ``chosen`` as a whole token at the SAME numeric-token index and as many
    numeric tokens as raw (tokens as ``parse.text.TOKEN_RE``; only digit-bearing tokens are
    counted; ``raw`` is the original string ``mt.src`` points into). A chosen token anywhere
    else in that reading confirms nothing. A variant with no confirmed occurrence is not applied."""
    original = raw if raw is not None else mt.text
    raw_spans = [(m.start(), m.end(), _has_digit(m.group())) for m in TOKEN_RE.finditer(original)]
    applied: list[NumericVariant] = []
    for v in variants:
        if not v.raw or not v.chosen or not ocr_confusable(v.raw, v.chosen):
            continue
        rx = _token_rx(v.raw)
        occ = list(rx.finditer(mt.text))
        if not occ:
            continue
        src_key = "ocr" if v.source == "ocr" else raw_source
        src_numeric = [t for t in TOKEN_RE.findall(sources.get(src_key, "")) if _has_digit(t)]
        ok = [
            m
            for m in occ
            if _confirmed_at(_numeric_index(raw_spans, mt.src[m.start()]), src_numeric, v.chosen)
        ]
        if not ok:
            continue
        b = _Builder()
        pos = 0
        for m in ok:
            for k in range(pos, m.start()):
                b.add(mt.text[k], mt.src[k], k in mt.optional)
            span = m.end() - m.start()
            for n, ch in enumerate(v.chosen):
                b.add(ch, mt.src[m.start() + min(n, span - 1)])
            pos = m.end()
        for k in range(pos, len(mt.text)):
            b.add(mt.text[k], mt.src[k], k in mt.optional)
        mt = b.build()
        applied.append(v)
    return mt, applied


# ---------------------------------------------------------------------------------------------
# level (a)


def _span(mt: MappedText, i: int, j: int, orig_len: int) -> tuple[int, int]:
    if i < j:
        seg = mt.src[i:j]
        return min(seg), max(seg) + 1
    p = mt.src[i] if i < len(mt.src) else orig_len
    return p, p


def _nonword(text: str, k: int) -> bool:
    if k < 0 or k >= len(text):
        return False
    ch = text[k]
    return not (ch.isalnum() or ch == "_")


def _violation(
    kind: FaithViolationKind,
    raw: str,
    clean: str,
    rs: tuple[int, int] | None,
    cs: tuple[int, int] | None,
) -> FaithfulnessViolation:
    return FaithfulnessViolation(
        kind=kind,
        raw_start=rs[0] if rs else None,
        raw_end=rs[1] if rs else None,
        clean_start=cs[0] if cs else None,
        clean_end=cs[1] if cs else None,
        raw=raw[rs[0] : rs[1]] if rs else "",
        clean=clean[cs[0] : cs[1]] if cs else "",
    )


def _numeric_violations(
    raw: str, clean: str, rc: MappedText, cc: MappedText
) -> list[FaithfulnessViolation]:
    out: list[FaithfulnessViolation] = []
    rm = [(m.group(0), m.start(), m.end()) for m in FAITH_NUM_RE.finditer(rc.text)]
    cm = [(m.group(0), m.start(), m.end()) for m in FAITH_NUM_RE.finditer(cc.text)]
    for mine, theirs, mt, side in ((rm, cm, rc, "raw"), (cm, rm, cc, "clean")):
        have = Counter(t for t, _, _ in theirs)
        for tok, a, z in mine:
            if have[tok] > 0:
                have[tok] -= 1
                continue
            sp = _span(mt, a, z, 0)
            if side == "raw":
                out.append(_violation(FaithViolationKind.numeric_mismatch, raw, clean, sp, None))
            else:
                out.append(_violation(FaithViolationKind.numeric_mismatch, raw, clean, None, sp))
    return out


def level_a(
    raw: str,
    clean: str,
    rc: MappedText,
    cc: MappedText,
    sm: SequenceMatcher[str] | None = None,
) -> list[FaithfulnessViolation]:
    """Violations of canonical raw vs canonical clean (design 4.4 steps 2-6)."""
    if rc.text == cc.text:
        return []
    # The two guards below skip the alignment and report one whole-text deletion, but numbers
    # are always compared: a rewrite or an oversize block that changed, dropped or added a
    # number still names it as numeric_mismatch. The numeric comparison is a linear regex scan
    # plus a multiset match, so it needs no size bound of its own.
    if len(rc.text) + len(cc.text) > FAITH_MAX_CHARS:
        return [
            _violation(FaithViolationKind.deletion, raw, clean, (0, len(raw)), (0, len(clean))),
            *_numeric_violations(raw, clean, rc, cc),
        ]
    sm = sm or SequenceMatcher(None, rc.text, cc.text, autojunk=False)
    if sm.quick_ratio() < FAITH_REWRITE_QUICK_RATIO:
        return [
            _violation(FaithViolationKind.deletion, raw, clean, (0, len(raw)), (0, len(clean))),
            *_numeric_violations(raw, clean, rc, cc),
        ]
    out: list[FaithfulnessViolation] = []
    ops = sm.get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        rs = _span(rc, i1, i2, len(raw))
        cs = _span(cc, j1, j2, len(clean))
        if tag == "delete":
            if all(k in rc.optional for k in range(i1, i2)):
                continue  # AE2: optional hyphen dropped
            if rc.text[i1:i2] == " " and (_nonword(rc.text, i1 - 1) or _nonword(rc.text, i2)):
                continue  # AE1
            out.append(_violation(FaithViolationKind.deletion, raw, clean, rs, cs))
        elif tag == "insert":
            if cc.text[j1:j2] == " " and (_nonword(cc.text, j1 - 1) or _nonword(cc.text, j2)):
                continue  # AE1
            out.append(_violation(FaithViolationKind.insertion, raw, clean, rs, cs))
        else:
            out.append(_violation(FaithViolationKind.deletion, raw, clean, rs, cs))
    out.extend(_numeric_violations(raw, clean, rc, cc))
    return out


def _sort_key(v: FaithfulnessViolation) -> tuple[int, int, str]:
    return (
        -1 if v.raw_start is None else v.raw_start,
        -1 if v.clean_start is None else v.clean_start,
        v.kind.value,
    )


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    if a0 == a1 or b0 == b1:
        return b0 <= a0 <= b1 if a0 == a1 else a0 <= b0 <= a1
    return a0 < b1 and b0 < a1


def build_diff(
    raw: str,
    clean: str,
    violations: Sequence[FaithfulnessViolation],
    moved: Sequence[tuple[tuple[int, int], tuple[int, int]]] = (),
) -> list[DiffOp]:
    """One DiffOp per opcode of original raw vs clean (the "Diff vs raw" view)."""
    if len(raw) + len(clean) > FAITH_MAX_CHARS:
        if raw == clean:
            return [
                DiffOp(
                    op=DiffOpKind.equal,
                    raw=raw,
                    clean=clean,
                    raw_start=0,
                    raw_end=len(raw),
                    clean_start=0,
                    clean_end=len(clean),
                    allowed=True,
                )
            ]
        return [
            DiffOp(
                op=DiffOpKind.replace,
                raw=raw,
                clean=clean,
                raw_start=0,
                raw_end=len(raw),
                clean_start=0,
                clean_end=len(clean),
                allowed=not violations,
            )
        ]
    if raw == clean:
        return (
            [
                DiffOp(
                    op=DiffOpKind.equal,
                    raw=raw,
                    clean=clean,
                    raw_start=0,
                    raw_end=len(raw),
                    clean_start=0,
                    clean_end=len(clean),
                    allowed=True,
                )
            ]
            if raw
            else []
        )
    out: list[DiffOp] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, raw, clean, autojunk=False).get_opcodes():
        kind = DiffOpKind(tag)
        allowed = True
        if tag != "equal":
            for v in violations:
                r_hit = (
                    tag in ("delete", "replace")
                    and v.raw_start is not None
                    and v.raw_end is not None
                    and _overlaps(i1, i2, v.raw_start, v.raw_end)
                )
                c_hit = (
                    tag in ("insert", "replace")
                    and v.clean_start is not None
                    and v.clean_end is not None
                    and _overlaps(j1, j2, v.clean_start, v.clean_end)
                )
                if r_hit or c_hit:
                    allowed = False
                    break
            if (
                allowed
                and moved
                and any(
                    (tag != "insert" and _overlaps(i1, i2, r0, r1))
                    or (tag != "delete" and _overlaps(j1, j2, c0, c1))
                    for (r0, r1), (c0, c1) in moved
                )
            ):
                kind = DiffOpKind.reorder
        out.append(
            DiffOp(
                op=kind,
                raw=raw[i1:i2],
                clean=clean[j1:j2],
                raw_start=i1,
                raw_end=i2,
                clean_start=j1,
                clean_end=j2,
                allowed=allowed,
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# level (b): reorder allowance


def loose(mt: MappedText) -> MappedText:
    """Every '-' between two letters deleted (src preserved)."""
    drop = [m.start() for m in _LOOSE_RE.finditer(mt.text)]
    if not drop:
        return mt
    return _delete_ranges(mt, [(k, k + 1) for k in drop])


def line_units(pre: MappedText) -> list[MappedText]:
    """Raw lines after AE5/AE3/AE4; an AE2 pair (letter-hyphen line end + letter line start)
    is one unit; each unit canonicalized with AE2 + AE1; empty units dropped."""
    spans = _lines(pre)
    merged: list[tuple[int, int]] = []
    k = 0
    while k < len(spans):
        a, z = spans[k]
        while (
            k + 1 < len(spans)
            and _AE2_LINE_END_RE.search(pre.text[a:z]) is not None
            and pre.text[spans[k + 1][0] : spans[k + 1][1]].lstrip(" \t")[:1].isalpha()
        ):
            k += 1
            z = spans[k][1]
        merged.append((a, z))
        k += 1
    out = [collapse(dehyphenate(pre.slice(a, z))) for a, z in merged]
    return [u for u in out if u.text]


def sentence_units(rc: MappedText) -> list[MappedText]:
    out: list[MappedText] = []
    pos = 0
    for m in _SENTENCE_SPLIT_RE.finditer(rc.text):
        out.append(rc.slice(pos, m.start()))
        pos = m.end()
    out.append(rc.slice(pos, len(rc.text)))
    return [u for u in out if u.text]


class _Budget(Exception):
    pass


def cover(
    units: Sequence[str], target: str, max_steps: int = REORDER_MAX_STEPS
) -> list[tuple[int, int]] | None:
    """A permutation of units that exactly tiles target (units separated by one ' ').
    Returns [(unit index, target position)] in target order, or None (also when the step
    budget is exceeded: fail closed)."""
    if not units:
        return None
    distinct: list[str] = list(dict.fromkeys(units))
    queues: dict[str, list[int]] = {u: [i for i, x in enumerate(units) if x == u] for u in distinct}
    used: dict[str, int] = {u: 0 for u in distinct}
    total = len(units)
    steps = 0
    perm: list[tuple[int, int]] = []

    def dfs(pos: int) -> bool:
        nonlocal steps
        if len(perm) == total:
            return pos == len(target) + 1
        for u in distinct:
            if used[u] >= len(queues[u]):
                continue
            steps += 1
            if steps > max_steps:
                raise _Budget
            end = pos + len(u)
            if target.startswith(u, pos) and (
                end == len(target) or (end < len(target) and target[end] == " ")
            ):
                perm.append((queues[u][used[u]], pos))
                used[u] += 1
                if dfs(end + 1):
                    return True
                used[u] -= 1
                perm.pop()
        return False

    try:
        return list(perm) if dfs(0) else None
    except _Budget:
        return None


def _find_unit(alt: str, unit: str, start: int) -> int:
    """First position >= start where ``unit`` occurs in ``alt`` as a whole unit: preceded by
    the start or a space and followed by a space or the end (both canonical, so whitespace is
    one ' '). ``5 Nm is the limit.`` is not found inside ``15 Nm is the limit.``."""
    q = alt.find(unit, start)
    while q >= 0:
        end = q + len(unit)
        if (q == 0 or alt[q - 1] == " ") and (end == len(alt) or alt[end] == " "):
            return q
        q = alt.find(unit, q + 1)
    return -1


def _attested(units_loose: Sequence[str], alt_loose: Sequence[str]) -> bool:
    """Some other reading contains every unit, as a whole unit, at strictly increasing
    positions (design 4.5 step 4)."""
    for alt in alt_loose:
        p = 0
        ok = True
        for u in units_loose:
            q = _find_unit(alt, u, p)
            if q < 0:
                ok = False
                break
            p = q + len(u)
        if ok:
            return True
    return False


@dataclass(frozen=True)
class _Reorder:
    units: list[MappedText]
    perm: list[int]
    clean_spans: list[tuple[int, int]]  # in clean original offsets, per perm position
    kind: str  # "line" | "sentence"


def _find_reorder(
    raw: str,
    clean: str,
    units: list[MappedText],
    cc: MappedText,
    kind: str,
) -> _Reorder | None:
    if not units or len(units) > REORDER_MAX_UNITS:
        return None
    lu = [loose(u).text for u in units]
    lc = loose(cc)
    tiled = cover(lu, lc.text)
    if tiled is None:
        return None
    perm = [i for i, _ in tiled]
    if perm == sorted(perm):
        return None
    spans: list[tuple[int, int]] = []
    for i, pos in tiled:
        a, z = _span(lc, pos, pos + len(lu[i]), len(clean))
        spans.append((a, z))
    raw_pi = concat([units[i] for i in perm])
    if level_a(raw, clean, raw_pi, cc):
        return None
    return _Reorder(units, perm, spans, kind)


# ---------------------------------------------------------------------------------------------
# entry point


@dataclass(frozen=True)
class FaithOutcome:
    result: FaithfulnessResult
    reordered: bool  # passed only through an evidence-backed reorder (signal value 0.9)


def _ratio(rc: MappedText, cc: MappedText, sm: SequenceMatcher[str] | None) -> float:
    if rc.text == cc.text:
        return 1.0
    if sm is None:
        return 0.0
    return round6(sm.ratio())


def _try_reorder(
    raw: str,
    clean: str,
    raw_canon: Canon,
    rc: MappedText,
    cc: MappedText,
    applied: Sequence[NumericVariant],
    sources: Mapping[str, str],
    raw_source: str,
    hf_strings: Sequence[str],
    block_type: BlockType,
    evidence: ReorderEvidence,
    page: int | None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> tuple[bool, list[tuple[tuple[int, int], tuple[int, int]]]] | None:
    """None: no permutation explains the failure. Else (accepted, moved unit spans)."""
    lines = [
        apply_variants(u, applied, sources, raw_source, raw)[0]
        for u in line_units(raw_canon.pre_ae2)
    ]
    candidates: list[_Reorder] = []
    for kind, units in (("line", lines), ("sentence", sentence_units(rc))):
        r = _find_reorder(raw, clean, units, cc, kind)
        if r is not None:
            candidates.append(r)
    if not candidates:
        return None
    alt_loose = [
        loose(
            canonicalize(
                t, hf_strings=hf_strings, block_type=block_type, page=page, hf_pages=hf_pages
            ).mt
        ).text
        for t in evidence.alt_texts
    ]
    # A reorder is accepted only when another independent reader (the other parser's text or
    # the OCR text of the same block) read the clean order. Layout risk (multi-column page,
    # displaced block, overlap) is never sufficient on its own: step order is a fact.
    chosen: _Reorder | None = None
    for r in candidates:
        in_order = [loose(r.units[i]).text for i in r.perm]
        if _attested(in_order, alt_loose):
            chosen = r
            break
    shown = chosen or candidates[0]
    keep = set(lis_keep(shown.perm))
    moved: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for pos, i in enumerate(shown.perm):
        if pos not in keep:
            u = shown.units[i]
            moved.append(((min(u.src), max(u.src) + 1), shown.clean_spans[pos]))
    return chosen is not None, moved


def check_faithfulness_ex(
    raw: str,
    clean: str,
    *,
    block_type: BlockType = BlockType.paragraph,
    table: TableData | None = None,
    hf_strings: Sequence[str] = (),
    variants: Sequence[NumericVariant] = (),
    variant_sources: Mapping[str, str] | None = None,
    raw_source: str = "",
    evidence: ReorderEvidence | None = None,
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> FaithOutcome:
    evidence = evidence or ReorderEvidence()
    sources = variant_sources or {}
    gfm = parse_gfm(clean) if (block_type == BlockType.table and table is not None) else None
    if gfm is not None and table is not None and any(len(row) != table.n_cols for row in gfm):
        gfm = None  # design 4.3: every GFM row has n_cols cells, else it is compared as text
    raw_canon: Canon | None = None
    if gfm is not None and table is not None:
        rc = table_raw_canon(table, raw)
        cc = table_clean_canon(gfm, clean)
    else:
        raw_canon = canonicalize(
            raw, hf_strings=hf_strings, block_type=block_type, page=page, hf_pages=hf_pages
        )
        rc = raw_canon.mt
        cc = canonicalize(
            clean,
            block_type=block_type,
            raw_deleted=raw_canon.hf_deleted,
            raw_rest=raw_canon.pre_ae2.text,
        ).mt
    rc, applied = apply_variants(rc, variants, sources, raw_source, raw)
    sm: SequenceMatcher[str] | None = None
    if rc.text != cc.text and len(rc.text) + len(cc.text) <= FAITH_MAX_CHARS:
        sm = SequenceMatcher(None, rc.text, cc.text, autojunk=False)
    violations = level_a(raw, clean, rc, cc, sm)
    if gfm is not None:
        violations.extend(table_coverage_violations(raw, clean, gfm))
    ratio = _ratio(rc, cc, sm)
    moved: list[tuple[tuple[int, int], tuple[int, int]]] = []
    reordered = False
    if (
        violations
        and raw_canon is not None
        and sm is not None
        and all(
            v.kind in (FaithViolationKind.insertion, FaithViolationKind.deletion)
            for v in violations
        )
    ):
        found = _try_reorder(
            raw,
            clean,
            raw_canon,
            rc,
            cc,
            applied,
            sources,
            raw_source,
            hf_strings,
            block_type,
            evidence,
            page,
            hf_pages,
        )
        if found is not None:
            accepted, spans = found
            if accepted:
                violations, moved, reordered = [], spans, True
            else:
                violations = [
                    _violation(FaithViolationKind.reorder, raw, clean, rs, cs) for rs, cs in spans
                ]
    violations = sorted(violations, key=_sort_key)
    result = FaithfulnessResult(
        passed=not violations,
        alignment_ratio=ratio,
        violations=violations,
        diff=build_diff(raw, clean, violations, moved),
        numeric_variants=list(applied),
    )
    return FaithOutcome(result, reordered)


def check_faithfulness(
    raw: str,
    clean: str,
    *,
    block_type: BlockType = BlockType.paragraph,
    table: TableData | None = None,
    hf_strings: Sequence[str] = (),
    variants: Sequence[NumericVariant] = (),
    variant_sources: Mapping[str, str] | None = None,
    raw_source: str = "",
    evidence: ReorderEvidence | None = None,
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> FaithfulnessResult:
    """Pure and deterministic; passed == no violations (design 4). ``page`` is the block's
    page number (AE3 footer templates such as ``Page {n}`` match only n == page);
    ``hf_pages`` maps each recorded header/footer string to the pages it was recorded on."""
    return check_faithfulness_ex(
        raw,
        clean,
        block_type=block_type,
        table=table,
        hf_strings=hf_strings,
        variants=variants,
        variant_sources=variant_sources,
        raw_source=raw_source,
        evidence=evidence,
        page=page,
        hf_pages=hf_pages,
    ).result
