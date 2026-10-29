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


@dataclass(frozen=True)
class HfTables:
    """Recorded header/footer strings that contain a letter (a bare number is never treated as
    a header/footer: deleting it could delete a value). ``templates`` maps the digit-normalized
    form (``hf_key``) to the recorded strings that have it."""

    exact: frozenset[str]
    templates: Mapping[str, tuple[str, ...]]


def hf_tables(hf_strings: Iterable[str]) -> HfTables:
    usable = sorted({collapse_ws(h) for h in hf_strings if any(c.isalpha() for c in h)})
    templates: dict[str, list[str]] = {}
    for h in usable:
        templates.setdefault(hf_key(h), []).append(h)
    return HfTables(frozenset(usable), {k: tuple(v) for k, v in templates.items()})


def is_hf_line(line: str, tables: HfTables, page: int | None) -> bool:
    """AE3: a raw line may be removed as a header/footer only if
    (a) it equals a recorded header/footer string (whitespace-collapsed), or
    (b)/(c) it has the digit template of a recorded string and every digit run that differs
        from that recorded string equals this block's page number (``Page {n}`` with
        n == page; ``Manual X200 Page {n}`` keeps X200 and changes only the page).
    Any other line, in particular one carrying another numeric token, is body text: deleting it
    is a ``deletion`` violation."""
    c = collapse_ws(line)
    if not c or not any(ch.isalpha() for ch in c):
        return False
    if c in tables.exact:
        return True
    recorded = tables.templates.get(hf_key(c), ())
    if not recorded:
        return False
    nums = _DIGIT_RUN_RE.findall(c)
    pg = str(page) if page is not None else None
    for rec in recorded:
        rec_nums = _DIGIT_RUN_RE.findall(rec)
        if len(rec_nums) == len(nums) and all(
            n == r or (pg is not None and n.lstrip("0") == pg)
            for n, r in zip(nums, rec_nums, strict=True)
        ):
            return True
    return False


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
    mt: MappedText, hf_strings: Sequence[str], page: int | None = None
) -> tuple[MappedText, list[HfDeleted]]:
    """AE3 on raw: delete whole lines that are a known header/footer (see is_hf_line)."""
    tables = hf_tables(hf_strings)
    if not tables.exact:
        return mt, []
    ranges: list[tuple[int, int]] = []
    deleted: list[HfDeleted] = []
    total = max(1, len(mt.text))
    for a, z in _lines(mt):
        line = mt.text[a:z]
        if is_hf_line(line, tables, page):
            ranges.append(_line_delete_range(mt, a, z))
            deleted.append(HfDeleted(collapse_ws(line), a / total))
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
    """AE3 on clean: remove what raw's deleted header/footer lines became, at most as many
    times as raw had them (multiset). Whole lines first; then inline surplus occurrences (the
    cleanup joined the line into its neighbours), nearest to the raw line's relative position."""
    if not deleted:
        return mt
    remaining = Counter(d.text for d in deleted)
    ranges: list[tuple[int, int]] = []
    for a, z in _lines(mt):
        c = collapse_ws(mt.text[a:z])
        if c and remaining[c] > 0:
            remaining[c] -= 1
            ranges.append(_line_delete_range(mt, a, z))
    mt = _delete_ranges(mt, _merge(ranges))
    total = max(1, len(mt.text))
    inline: list[tuple[int, int]] = []
    for text in sorted(t for t, n in remaining.items() if n > 0):
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
        inline.extend(occ[k] for k in sorted(chosen))
    return _delete_ranges(mt, _merge(inline))


def normalize_bullets(mt: MappedText, block_type: BlockType) -> MappedText:
    """AE4: a line-start bullet glyph followed by whitespace (or the end of the text) becomes the
    canonical bullet. "Whitespace" is the same notion AE1 collapses, so that canonicalization is
    idempotent (a glyph alone on its line is a line-start glyph again after the collapse)."""
    glyphs = BULLETS + (LIST_OCR_BULLETS if block_type == BlockType.list else "")
    chars = list(mt.text)
    n = len(chars)
    for a, z in _lines(mt):
        k = a
        while k < z and chars[k].isspace():
            k += 1
        if k < z and chars[k] in glyphs and (k + 1 == n or chars[k + 1].isspace()):
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
) -> Canon:
    """Steps 1-5 of design 4.2. With raw_deleted=None this is the raw side (AE3 deletes known
    header/footer lines); otherwise the clean side (AE3 removes what raw deleted)."""
    mt = glyph_identity(s)
    deleted: list[HfDeleted] = []
    if raw_deleted is None:
        mt, deleted = strip_hf_raw(mt, hf_strings, page)
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


# ---------------------------------------------------------------------------------------------
# numeric variants


def _token_rx(tok: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)")


def _token_index(spans: Sequence[tuple[int, int]], offset: int) -> int:
    """Index of the token containing ``offset`` (else the number of tokens before it)."""
    for k, (a, z) in enumerate(spans):
        if a <= offset < z:
            return k
        if a > offset:
            return k
    return len(spans)


def _confirmed_at(i: int, src_tokens: Sequence[str], chosen_rx: re.Pattern[str]) -> bool:
    """The source reading has the chosen token at token index i +- 1."""
    return any(
        0 <= j < len(src_tokens) and chosen_rx.search(src_tokens[j]) is not None
        for j in (i - 1, i, i + 1)
    )


def apply_variants(
    mt: MappedText,
    variants: Sequence[NumericVariant],
    sources: Mapping[str, str],
    raw_source: str,
    raw: str | None = None,
) -> tuple[MappedText, list[NumericVariant]]:
    """Replace each whole-token occurrence of a variant's raw that is *confirmed*: the source
    reading has the chosen token at the aligned position (same token index +- 1, tokens as
    ``parse.text.TOKEN_RE``; ``raw`` is the original string ``mt.src`` points into). A chosen
    token elsewhere in that reading confirms nothing. A variant with no confirmed occurrence is
    not applied."""
    original = raw if raw is not None else mt.text
    raw_spans = [m.span() for m in TOKEN_RE.finditer(original)]
    applied: list[NumericVariant] = []
    for v in variants:
        if not v.raw or not v.chosen:
            continue
        rx = _token_rx(v.raw)
        occ = list(rx.finditer(mt.text))
        if not occ:
            continue
        src_key = "ocr" if v.source == "ocr" else raw_source
        src_tokens = TOKEN_RE.findall(sources.get(src_key, ""))
        chosen_rx = _token_rx(v.chosen)
        ok = [
            m
            for m in occ
            if _confirmed_at(_token_index(raw_spans, mt.src[m.start()]), src_tokens, chosen_rx)
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
    if len(rc.text) + len(cc.text) > FAITH_MAX_CHARS:
        return [_violation(FaithViolationKind.deletion, raw, clean, (0, len(raw)), (0, len(clean)))]
    sm = sm or SequenceMatcher(None, rc.text, cc.text, autojunk=False)
    if sm.quick_ratio() < FAITH_REWRITE_QUICK_RATIO:
        return [_violation(FaithViolationKind.deletion, raw, clean, (0, len(raw)), (0, len(clean)))]
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


def _attested(units_loose: Sequence[str], alt_loose: Sequence[str]) -> bool:
    for alt in alt_loose:
        p = 0
        ok = True
        for u in units_loose:
            q = alt.find(u, p)
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
        loose(canonicalize(t, hf_strings=hf_strings, block_type=block_type, page=page).mt).text
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
        raw_canon = canonicalize(raw, hf_strings=hf_strings, block_type=block_type, page=page)
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
) -> FaithfulnessResult:
    """Pure and deterministic; passed == no violations (design 4). ``page`` is the block's
    page number (AE3 footer templates such as ``Page {n}`` match only n == page)."""
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
    ).result
