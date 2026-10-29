"""Deterministic cleanup passes (design 2). Every pass is a pure ``(text, ctx) -> str`` with a
fixed name; ``PASSES`` is their fixed order. A pass only makes edits inside one allowed-edit
class of the faithfulness check (AE1-AE6), and its output is still checked (verify.py).

Never touched: numeric tokens, part numbers, tolerances, table cell text (beyond
``norm_cell``), heading and caption text beyond whitespace."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from manuallabor.cleanup.lexicon import Lexicon
from manuallabor.cleanup.types import (
    AMBIGUOUS_PREFIXES,
    ENUM_RE,
    UNAMBIGUOUS_BULLETS,
    LearnedRule,
)
from manuallabor.contracts.block import TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.tables import table_markdown_from_data
from manuallabor.scoring.faithfulness import (
    BULLETS,
    CANON_BULLET,
    LIST_OCR_BULLETS,
    HfTables,
    glyph_identity,
    hf_edge_lines,
    hf_tables,
    sign_before_number,
)

# letter run - line break - letter run; both runs whole words (a part number such as
# ``4471A-\nB`` or ``M8-\nbolt`` never matches: the run must not touch a digit)
DH_RE: Final = re.compile(r"(?<!\w)(?P<L>[^\W\d_]+)-[ \t]*\n[ \t]*(?P<R>[^\W\d_]+)(?!\w)")
_HSPACE_RE: Final = re.compile(r"[ \t]+")
# private-use sentinel standing in for a line break that the LLM is asked to decide (3.2)
AMBIGUOUS_MARK: Final = ""

_EMPTY_HF: Final = hf_tables(())


@dataclass(frozen=True)
class PassCtx:
    """Everything a pass may look at besides the text (pure inputs)."""

    block_type: BlockType = BlockType.paragraph
    page: int | None = None
    hf: HfTables = _EMPTY_HF
    lexicon: Lexicon = field(default_factory=Lexicon)
    table: TableData | None = None
    # dehyphenation (D5): replace the dropped break by AMBIGUOUS_MARK so the LLM input keeps it
    mark_ambiguous: bool = False


PassFn = Callable[[str, PassCtx], str]


@dataclass(frozen=True)
class Pass:
    name: str
    fn: PassFn


# ---------------------------------------------------------------------------------------------
# P0-P7


def crlf(text: str, ctx: PassCtx) -> str:
    """P0 (AE1): CRLF and lone CR become LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def unicode_pass(text: str, ctx: PassCtx) -> str:
    """P1 (AE5): NFC per combining sequence, ligatures to letters, soft hyphen deleted,
    NBSP-like spaces to ' '. Exactly the checker's glyph identity; never NFKC (``mm²``,
    ``½`` and ``µm`` stay)."""
    return glyph_identity(text).text


def strip_hf(text: str, ctx: PassCtx) -> str:
    """P2 (AE3): delete a recorded header/footer line on this page (the checker's own
    predicates ``is_hf_line`` + ``hf_edge_lines``): only the first or last non-blank line (a
    leading/trailing remnant), never one in the interior, and never every line of the block
    (a paragraph or heading that is only the running header stays; keeping a header line is
    always allowed)."""
    if not ctx.hf.exact:
        return text
    lines = text.split("\n")
    drop = hf_edge_lines(lines, ctx.hf, ctx.page)
    if not drop:
        return text
    return "\n".join(ln for k, ln in enumerate(lines) if k not in drop)


def bullet_glyphs(block_type: BlockType) -> str:
    """The glyphs P3 turns into ``•`` (and the only ones the LLM may turn into ``•``, V2)."""
    return BULLETS + LIST_OCR_BULLETS if block_type == BlockType.list else UNAMBIGUOUS_BULLETS


def line_bullet(line: str, glyphs: str) -> re.Match[str] | None:
    """A line-start glyph (after indentation) followed by spaces/tabs or the line end, that is
    not the sign of a number (``+ 5 V``, ``- 12 V``: AE4 ``sign_before_number``)."""
    if not glyphs:
        return None
    m = re.match(r"([ \t]*)([" + re.escape(glyphs) + r"])([ \t]+|$)", line)
    if m is None or sign_before_number(m.group(2), line[m.end(2) :]):
        return None
    return m


def normalize_glyphs(text: str, glyphs: str) -> str:
    """A line-start glyph (after indentation) followed by spaces/tabs becomes ``• ``; a glyph
    alone at a line end becomes ``•``; a sign before a number stays. Anything else is left as
    it is."""
    if not glyphs:
        return text
    out = []
    for ln in text.split("\n"):
        m = line_bullet(ln, glyphs)
        if m is not None:
            ln = m.group(1) + CANON_BULLET + (" " if m.group(3) else "") + ln[m.end() :]
        out.append(ln)
    return "\n".join(out)


def bullets(text: str, ctx: PassCtx) -> str:
    """P3 (AE4): in list blocks every AE4 glyph incl. the OCR readings ``¢ + o «``; elsewhere
    only the unambiguous ``•◦▪‣●`` (``– 40 °C`` and ``* note`` in prose stay). A sign before a
    number is never a bullet (``+ 5 V`` in a list stays)."""
    return normalize_glyphs(text, bullet_glyphs(ctx.block_type))


def dh_decide(left: str, right: str, lexicon: Lexicon) -> tuple[bool, str]:
    """(keep the hyphen, rule) for ``left-\\nright`` (D2-D6; D1 is the learned pass)."""
    if right[:1].isupper():
        return True, "keep_upper"
    if lexicon.has_compound(left, right) and not lexicon.has_word(left + right):
        return True, "keep_lexicon"
    if lexicon.has_word(left + right):
        return False, "drop_lexicon"
    if left.casefold() in AMBIGUOUS_PREFIXES:
        return False, "drop_ambiguous"
    return False, "drop_default"


def dehyphenate_ex(text: str, ctx: PassCtx) -> tuple[str, list[str]]:
    """P4 (AE2): resolve each ``L-\\nR`` break. Returns the text and the decisions
    (``rule:word``) in text order. Repeats until no break is left, so it is idempotent."""
    decisions: list[str] = []

    def sub(m: re.Match[str]) -> str:
        left, right = m.group("L"), m.group("R")
        keep, rule = dh_decide(left, right, ctx.lexicon)
        if rule == "drop_ambiguous" and ctx.mark_ambiguous:
            word = f"{left}-{AMBIGUOUS_MARK}{right}"
            decisions.append(f"{rule}:{left}{right}")
            return word
        word = f"{left}-{right}" if keep else f"{left}{right}"
        decisions.append(f"{rule}:{word}")
        return word

    prev = None
    while prev != text:
        prev = text
        text = DH_RE.sub(sub, text)
    return text, decisions


def dehyphenate(text: str, ctx: PassCtx) -> str:
    return dehyphenate_ex(text, ctx)[0]


def is_item_start(line: str) -> bool:
    """A line that opens a list item: ``• `` (or a lone ``•``) or an enumerator."""
    if line[:1] == CANON_BULLET and (len(line) == 1 or line[1] == " "):
        return True
    return ENUM_RE.match(line) is not None


def _checker_bullet(line: str, block_type: BlockType) -> bool:
    """The faithfulness check reads this line start as a bullet (AE4: any of its glyphs, the
    OCR ones only in lists, followed by whitespace or the line end). Joining such a line into
    the previous one would move the glyph off the line start and change its canonical form,
    so the line break before it is kept."""
    glyphs = BULLETS + (LIST_OCR_BULLETS if block_type == BlockType.list else "")
    return (
        line[:1] in glyphs
        and (len(line) == 1 or line[1].isspace())
        and not sign_before_number(line[0], line[1:])
    )


def _glue(prev: str, nxt: str) -> bool:
    """``P/N 4471-`` + ``A``: a line ending in ``-`` right after an alphanumeric and a next line
    starting with one join with no space (AE1 allows it next to the non-word ``-``)."""
    return len(prev) >= 2 and prev[-1] == "-" and prev[-2].isalnum() and nxt[:1].isalnum()


def _join(prev: str, nxt: str) -> str:
    return prev + nxt if _glue(prev, nxt) else prev + " " + nxt


_AE2_END_RE: Final = re.compile(r"[^\W\d_]-$")
_LETTER_START_RE: Final = re.compile(r"^[^\W\d_]")


def join_kept(lines: Sequence[str]) -> str:
    """Kept lines joined by ``\n``, except that a line ending ``letter-`` before a line
    starting with a letter is separated by a blank line: the passes never create an AE2 line
    break that the raw text did not have (a dropped blank line would hand dehyphenation a new
    break on the next run, and the check would not accept that join)."""
    out = lines[0] if lines else ""
    for prev, nxt in zip(lines, lines[1:], strict=False):
        sep = "\n\n" if _AE2_END_RE.search(prev) and _LETTER_START_RE.match(nxt) else "\n"
        out += sep + nxt
    return out


def _lines(text: str) -> list[str]:
    return [ln for ln in (x.strip(" \t") for x in text.split("\n")) if ln]


def join_lines(text: str, ctx: PassCtx) -> str:
    """P5 (AE1): paragraph wraps become one space (kept before ``• ``/enumerator lines); list
    continuations join their item (a list without any item marker keeps every line); heading
    and caption lines join with one space. Blank lines are dropped. A line the checker reads
    as a bullet line is never joined (see ``_checker_bullet``)."""
    lines = _lines(text)
    if not lines:
        return text
    t = ctx.block_type
    if t == BlockType.list and not any(is_item_start(ln) for ln in lines):
        return join_kept(lines)
    out = [lines[0]]
    for ln in lines[1:]:
        if _checker_bullet(ln, t) or (
            t not in (BlockType.heading, BlockType.caption) and is_item_start(ln)
        ):
            out.append(ln)
        elif t in (BlockType.heading, BlockType.caption):
            out[-1] = out[-1] + " " + ln
        else:
            out[-1] = _join(out[-1], ln)
    return join_kept(out)


def whitespace(text: str, ctx: PassCtx) -> str:
    """P6 (AE1): runs of spaces/tabs become one space, lines are stripped, blank lines are
    dropped (newline runs become one newline), both ends stripped."""
    lines = [_HSPACE_RE.sub(" ", ln).strip(" \t") for ln in text.split("\n")]
    return join_kept([ln for ln in lines if ln])


def table(text: str, ctx: PassCtx) -> str:
    """P7 (AE6): the GFM grid rendered from TableData (cells only ``norm_cell``ed)."""
    if ctx.table is None:
        return text
    return table_markdown_from_data(ctx.table)


# ---------------------------------------------------------------------------------------------
# learned passes (design 7): hyphen exceptions (D1) and extra bullet glyphs


def learned_hyphen(rule: LearnedRule) -> PassFn:
    """``hyphen_keep``/``hyphen_drop`` for one ``L-R`` (casefold): an AE2 break of exactly that
    pair is kept (``L-R``) or dropped (``LR``). Runs before P4 so it wins (D1)."""
    left, right = rule.value.casefold().split("-", 1)
    keep = rule.kind == "hyphen_keep"

    def fn(text: str, ctx: PassCtx) -> str:
        def sub(m: re.Match[str]) -> str:
            lw, rw = m.group("L"), m.group("R")
            if lw.casefold() != left or rw.casefold() != right:
                return m.group(0)
            return f"{lw}-{rw}" if keep else f"{lw}{rw}"

        return DH_RE.sub(sub, text)

    return fn


def learned_bullet(rule: LearnedRule) -> PassFn:
    glyph = rule.value

    def fn(text: str, ctx: PassCtx) -> str:
        return normalize_glyphs(text, glyph)

    return fn


# ---------------------------------------------------------------------------------------------
# plan


P_CRLF = Pass("crlf", crlf)
P_UNICODE = Pass("unicode", unicode_pass)
P_STRIP_HF = Pass("strip_hf", strip_hf)
P_BULLETS = Pass("bullets", bullets)
P_DEHYPHENATE = Pass("dehyphenate", dehyphenate)
P_JOIN = Pass("join_lines", join_lines)
P_WHITESPACE = Pass("whitespace", whitespace)
P_TABLE = Pass("table", table)
PASSES: Final = (
    P_CRLF,
    P_UNICODE,
    P_STRIP_HF,
    P_BULLETS,
    P_DEHYPHENATE,
    P_JOIN,
    P_WHITESPACE,
    P_TABLE,
)

_TEXT = (BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.other)
# pass name -> block types it applies to (table: only without TableData, except P7)
APPLIES: Final[Mapping[str, frozenset[BlockType]]] = {
    "crlf": frozenset((*_TEXT, BlockType.caption, BlockType.table)),
    "unicode": frozenset((*_TEXT, BlockType.table)),
    "strip_hf": frozenset(_TEXT),
    "bullets": frozenset((BlockType.paragraph, BlockType.list)),
    "dehyphenate": frozenset((BlockType.paragraph, BlockType.list)),
    "join_lines": frozenset(
        (BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.caption)
    ),
    "whitespace": frozenset((*_TEXT, BlockType.caption, BlockType.table)),
    "table": frozenset((BlockType.table,)),
}


def plan_passes(
    block_type: BlockType, has_table: bool, rules: Sequence[LearnedRule] = ()
) -> list[Pass]:
    """The passes for one block, in the fixed order, with the learned passes in place: extra
    bullet glyphs right after P3, hyphen exceptions right before P4."""
    if block_type == BlockType.table and has_table:
        return [P_TABLE]
    out: list[Pass] = []
    for p in PASSES:
        if p.name == "table" or block_type not in APPLIES[p.name]:
            continue
        if p.name == "dehyphenate":
            out.extend(
                Pass(f"learned:{r.id}", learned_hyphen(r))
                for r in rules
                if r.kind in ("hyphen_keep", "hyphen_drop") and block_type in r.block_types
            )
        out.append(p)
        if p.name == "bullets":
            out.extend(
                Pass(f"learned:{r.id}", learned_bullet(r))
                for r in rules
                if r.kind == "bullet_glyph" and block_type in r.block_types
            )
    return out


@dataclass(frozen=True)
class DetResult:
    text: str
    applied: list[str]  # names of the passes that changed the text, in order
    dh: list[str]  # dehyphenation decisions


def apply_pass(p: Pass, text: str, ctx: PassCtx) -> tuple[str, list[str]]:
    if p.name == "dehyphenate":
        return dehyphenate_ex(text, ctx)
    return p.fn(text, ctx), []


def compose(text: str, passes: Sequence[Pass], ctx: PassCtx) -> DetResult:
    applied: list[str] = []
    dh: list[str] = []
    for p in passes:
        out, d = apply_pass(p, text, ctx)
        if out != text:
            applied.append(p.name)
            dh.extend(d)
        text = out
    return DetResult(text, applied, dh)


def restore_marks(text: str) -> str:
    return text.replace(AMBIGUOUS_MARK, "\n")
