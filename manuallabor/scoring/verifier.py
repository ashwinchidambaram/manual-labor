"""Optional llm_verifier: a separate model as a second reader (SPEC 5.1, design 2.10).

The verifier is never asked about its own output (skipped when it is the cleanup model) and
never asked to rate anything; its answer is validated strictly before it becomes a signal.
It is only asked when cleanup changed a canonical token, and its answer only counts when the
span it quotes lies on a place where raw and clean differ (design 2.10, revision 2026-10-30)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final, Literal

from manuallabor.contracts.block import Signal
from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import BlockType, SignalName, Task
from manuallabor.contracts.llm import Message
from manuallabor.parse.text import collapse_ws
from manuallabor.providers.base import RAW_CLOSE, RAW_OPEN, ProviderError, ProviderSet
from manuallabor.scoring.faithfulness import GFM_SEP_RE, MappedText, canonicalize, loose
from manuallabor.scoring.types import (
    DETAIL_MAX,
    VERIFIER_FLAG_VALUE,
    VERIFIER_MAX_SPAN,
    VERIFIER_MIN_SPAN,
)

VERIFIER_SYSTEM: Final = (
    "You compare two versions of a passage from a technical manual: the raw extraction and "
    "a cleaned version. Report only differences in facts, numbers, units, part numbers or "
    "steps. Reply with the exact differing span copied from the text, or the single word NONE."
)
QUESTION: Final = (
    "Does the cleaned text change any fact, number, or step? Answer with the differing span or NONE"
)
_NONE_RE: Final = re.compile(r"(?i)none\.?")
_WHOLE_NUMBER_RE: Final = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?!\w)")
FUNCTION_WORDS: Final = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "then",
        "this",
        "to",
        "was",
        "were",
        "with",
    ]
)

Outcome = Literal[
    "ok",
    "flag",
    "skip_no_clean",
    "skip_unchanged",
    "skip_faith_failed",
    "skip_no_verifier",
    "skip_same_model",
    "verifier_invalid",
    "verifier_errors",
]


# A canonical token: a word run, or one punctuation glyph. Table pipes and the canonical bullet
# are structure, not text (as ``TOKEN_RE`` and the AE6 coverage check treat them). Splitting
# punctuation off words matches AE1, which lets a space appear or vanish next to a non-word
# character ("(see" vs "( see"), so such a space is never a difference here either.
_CANON_TOKEN_RE: Final = re.compile(r"\w+|[^\w\s|•]")
FRAGMENT_MAX: Final = 48  # chars of each quoted fragment in the detail before it is shortened


@dataclass(frozen=True)
class Tok:
    """One canonical token and the span of the original string it came from."""

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Change:
    """One place where the canonical tokens of raw and clean differ (a difflib opcode that is
    not ``equal``): token index ranges on each side, and the original text of each side."""

    raw_toks: tuple[int, int]
    clean_toks: tuple[int, int]
    raw: str
    clean: str


@dataclass(frozen=True)
class TokenPair:
    raw: tuple[Tok, ...]
    clean: tuple[Tok, ...]
    changes: tuple[Change, ...]

    @property
    def unchanged(self) -> bool:
        return not self.changes


def _separator_ranges(s: str) -> list[tuple[int, int]]:
    """Spans of GFM separator rows (``|---|---|``): table syntax that cleanup adds (AE6)."""
    out: list[tuple[int, int]] = []
    pos = 0
    for line in s.split("\n"):
        if line.strip() and GFM_SEP_RE.match(line.strip()):
            out.append((pos, pos + len(line)))
        pos += len(line) + 1
    return out


def _tokens(s: str, mt: MappedText) -> tuple[Tok, ...]:
    mt = loose(mt)  # AE2: a hyphen kept or dropped between two letters is the same word
    seps = _separator_ranges(s)
    out: list[Tok] = []
    for m in _CANON_TOKEN_RE.finditer(mt.text):
        a, z = mt.src[m.start()], mt.src[m.end() - 1] + 1
        if any(x <= a < y for x, y in seps):
            continue
        out.append(Tok(m.group(), a, z))
    return tuple(out)


def _fragment(s: str, toks: Sequence[Tok], i: int, j: int) -> str:
    return collapse_ws(s[toks[i].start : toks[j - 1].end]) if i < j else ""


def token_pair(
    raw: str,
    clean: str,
    *,
    block_type: BlockType = BlockType.paragraph,
    hf_strings: Sequence[str] = (),
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> TokenPair:
    """Canonical tokens of raw and clean and where they differ. The canonicalisation is the
    faithfulness check's own (``canonicalize``: AE5 glyphs, AE3 headers/footers, AE4 bullets,
    AE2 hyphenation, AE1 whitespace) with the same arguments, so an allowed edit is never a
    difference; the diff is ``difflib`` on token texts, deterministic."""
    rcan = canonicalize(
        raw, hf_strings=hf_strings, block_type=block_type, page=page, hf_pages=hf_pages
    )
    ccan = canonicalize(
        clean,
        block_type=block_type,
        raw_deleted=rcan.hf_deleted,
        raw_rest=rcan.pre_ae2.text,
    )
    rt, ct = _tokens(raw, rcan.mt), _tokens(clean, ccan.mt)
    sm = SequenceMatcher(None, [t.text for t in rt], [t.text for t in ct], autojunk=False)
    changes = tuple(
        Change((i1, i2), (j1, j2), _fragment(raw, rt, i1, i2), _fragment(clean, ct, j1, j2))
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )
    return TokenPair(rt, ct, changes)


def _occurrences(needle: Sequence[str], hay: Sequence[Tok]) -> list[tuple[int, int]]:
    k = len(needle)
    if not k:
        return []
    return [
        (p, p + k)
        for p in range(len(hay) - k + 1)
        if all(hay[p + n].text == needle[n] for n in range(k))
    ]


def _touches(occ: tuple[int, int], side: tuple[int, int]) -> bool:
    """A quoted token range [a, b) lies on a change [i, j) of the same side. A change that is
    empty on this side (tokens only the other side has) sits between tokens i-1 and i; a quote
    that includes either neighbour marks it."""
    a, b = occ
    i, j = side
    if i == j:
        i, j = i - 1, i + 1
    return a < j and i < b


def _change_for(span: str, pair: TokenPair) -> Change | None:
    """The first change (in raw order) that an occurrence of the span's canonical tokens marks,
    on the raw side or the clean side; None when every occurrence is in unchanged text."""
    needle = [t.text for t in _tokens(span, canonicalize(span).mt)]
    hits_raw = _occurrences(needle, pair.raw)
    hits_clean = _occurrences(needle, pair.clean)
    for ch in pair.changes:
        if any(_touches(o, ch.raw_toks) for o in hits_raw) or any(
            _touches(o, ch.clean_toks) for o in hits_clean
        ):
            return ch
    return None


def _shorten(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def evidence_detail(span: str, change: Change) -> str:
    """``verifier quoted "<span>"; raw "<raw fragment>" -> clean "<clean fragment>"``. Each
    quoted part is a JSON string literal, so the panel reads it back exactly; the parts are
    shortened (never the literal cut) until the detail fits DETAIL_MAX."""
    cap = FRAGMENT_MAX
    while True:
        q = [
            json.dumps(_shorten(x, cap), ensure_ascii=False)
            for x in (span, change.raw, change.clean)
        ]
        detail = f"verifier quoted {q[0]}; raw {q[1]} -> clean {q[2]}"
        if len(detail) <= DETAIL_MAX or cap <= 8:
            return detail
        cap -= 8


def same_model(a: ModelRef, b: ModelRef) -> bool:
    return (a.provider, a.model, a.api_base) == (b.provider, b.model, b.api_base)


def verifier_messages(raw: str, clean: str) -> list[Message]:
    return [
        Message(role="system", content=VERIFIER_SYSTEM),
        Message(
            role="user",
            content=f"{RAW_OPEN}{raw}{RAW_CLOSE}\n<clean>{clean}</clean>\n{QUESTION}",
        ),
    ]


def _unwrap(text: str) -> str:
    out = text.strip()
    for q in ('"', "'", "`"):
        if len(out) >= 2 and out[0] == q and out[-1] == q:
            return out[1:-1].strip()
    return out


def _weak(span: str) -> bool:
    """Too little to be a differing span: under VERIFIER_MIN_SPAN chars, no letter or digit,
    or nothing but common function words (``e``, ``.``, ``the``, ``of the``)."""
    if len(span) < VERIFIER_MIN_SPAN or not any(c.isalnum() for c in span):
        return True
    words = [w.strip(".,;:!?()[]'\"").casefold() for w in span.split()]
    return all(w in FUNCTION_WORDS or not w for w in words)


def _short_numeric(span: str, raw: str, clean: str) -> bool:
    """A 1-2 char span that is a whole numeric token of raw or clean (``35``, ``5``): a
    number is a fact even when short. ``3`` inside ``35`` is not one."""
    if len(span) >= VERIFIER_MIN_SPAN or not span.isdigit():
        return False
    return span in _WHOLE_NUMBER_RE.findall(raw) or span in _WHOLE_NUMBER_RE.findall(clean)


def validate_answer(
    text: str,
    raw: str,
    clean: str,
    *,
    pair: TokenPair | None = None,
    block_type: BlockType = BlockType.paragraph,
    hf_strings: Sequence[str] = (),
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> tuple[Outcome, Signal | None]:
    """Strict. Only a found differing span is evidence, and it can only lower the score:
    - NONE -> ("ok", None): no signal at all (a 1.0 soft signal would raise the geometric mean
      of the soft signals and could lift a block over the threshold);
    - a verbatim span of raw or clean, 3..300 chars, not a bare function word, or a 1-2 char
      span that is a whole numeric token of raw or clean (``35``, ``5``), AND whose canonical
      tokens lie on a place where raw and clean differ -> 0.2 soft, with the differing raw and
      clean fragments in the detail;
    - anything else (free text, weak spans such as ``e``/``.``/``the``, a span found only in
      text that both versions share) -> discarded."""
    out = _unwrap(text)
    if _NONE_RE.fullmatch(out):
        return "ok", None
    span = collapse_ws(out)
    if (
        len(out) > VERIFIER_MAX_SPAN
        or re.search(r"\n[ \t]*\n", out) is not None
        or not (
            _short_numeric(span, raw, clean)
            or (not _weak(span) and (span in collapse_ws(clean) or span in collapse_ws(raw)))
        )
    ):
        return "verifier_invalid", None
    if pair is None:
        pair = token_pair(
            raw, clean, block_type=block_type, hf_strings=hf_strings, page=page, hf_pages=hf_pages
        )
    change = _change_for(span, pair)
    if change is None:
        return "verifier_invalid", None  # verbatim in text both versions share: no evidence
    return "flag", Signal(
        name=SignalName.llm_verifier,
        value=VERIFIER_FLAG_VALUE,
        critical=False,
        detail=evidence_detail(span, change),
    )


@dataclass(frozen=True)
class VerifierPlan:
    """Whether the verifier may run for this project, and the provider set getter."""

    ref: ModelRef | None
    reason: Outcome | None  # skip reason for every block when ref is None
    providers: Callable[[], ProviderSet] | None


def plan_verifier(
    config: ProjectConfig, providers: Callable[[], ProviderSet] | None
) -> VerifierPlan:
    ref = config.model_for(Task.verifier)
    if ref is None:
        return VerifierPlan(None, "skip_no_verifier", None)
    cleanup = config.model_for(Task.cleanup)
    if cleanup is not None and same_model(ref, cleanup):
        return VerifierPlan(None, "skip_same_model", None)
    return VerifierPlan(ref, None, providers)


def llm_verifier(
    raw: str,
    clean: str | None,
    *,
    faith_passed: bool,
    plan: VerifierPlan,
    block_type: BlockType = BlockType.paragraph,
    hf_strings: Sequence[str] = (),
    page: int | None = None,
    hf_pages: Mapping[str, Sequence[int]] | None = None,
) -> tuple[Outcome, Signal | None]:
    """The canonicalisation arguments are the faithfulness check's own for this block, so an
    edit that check allows (whitespace, hyphenation, headers/footers, bullets, glyphs, table
    pipes) never counts as a change worth asking about."""
    if clean is None:
        return "skip_no_clean", None
    if clean == raw:
        return "skip_unchanged", None
    if not faith_passed:
        return "skip_faith_failed", None
    if plan.ref is None or plan.providers is None:
        return plan.reason or "skip_no_verifier", None
    # computed only when a call would follow (scoring without a verifier stays as fast)
    pair = token_pair(
        raw, clean, block_type=block_type, hf_strings=hf_strings, page=page, hf_pages=hf_pages
    )
    if pair.unchanged:
        return "skip_unchanged", None
    try:
        res = plan.providers().get(Task.verifier).chat(Task.verifier, verifier_messages(raw, clean))
    except ProviderError:
        return "verifier_errors", None
    return validate_answer(res.text, raw, clean, pair=pair)
