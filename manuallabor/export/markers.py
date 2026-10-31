"""Review markers (design 11 sections 20 and 20.11). Pure.

A marker is an HTML comment on a line of its own, the first line of every exported paragraph's
unit: a blank line above it, the paragraph directly below it. Every text block has one, whatever
its status (approved, edited, auto-approved, overridden); figure blocks have none. Renderers show
nothing; `grep '^<!-- ml: '` lists the paragraphs; the block id leads to the review sidecar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

from manuallabor.contracts.article import ArticleReview, ArticleReviewCounts, BlockReview
from manuallabor.contracts.enums import BlockType
from manuallabor.state.models import ExportMarkers

__all__ = [
    "MARKER_LIKE_RE",
    "MARKER_PREFIX",
    "MARKER_RE",
    "SOURCE_MARKER_RE",
    "STATUS_WORD",
    "Marker",
    "encode_reason",
    "marker_line",
    "misplaced_markers",
    "needs_marker",
    "parse_marker",
    "tally_markers",
]

MARKER_PREFIX: Final = "<!-- ml:"
# anything a reader or a grep could take for a marker: an HTML comment opening that starts with
# "ml:", spacing and case aside. An odd run of backslashes before `<` makes it literal text
# (CommonMark punctuation escape), which is how alt text carries a `<`; an even run does not.
MARKER_LIKE_RE: Final = re.compile(r"(?<!\\)(?:\\\\)*<!--\s*ml\s*:", re.IGNORECASE)
# the same in source text, backslashes or not: block text and titles holding it are refused
SOURCE_MARKER_RE: Final = re.compile(r"<!--\s*ml\s*:", re.IGNORECASE)
MARKER_RE: Final = re.compile(
    r"^<!-- ml: (?P<status>approved|edited|auto-approved|overridden); block: "
    r"(?P<block>b-[a-z0-9-]+-p\d{3,}-\d{2,})"
    r"(?:; flag: (?P<flag>flag-\d{6}))?"
    r"(?:; reason: (?P<reason>\"(?:[^\"\\]|\\.)*\"))? -->$"
)
STATUS_WORD: Final = {
    "approved": "approved",
    "edited": "edited",
    "auto_approved": "auto-approved",
    "overridden": "overridden",
}
_SIDECAR_STATUS: Final = {w: s for s, w in STATUS_WORD.items()}
_LINE_BREAKS: Final = {"\u2028", "\u2029", "\x85"}


def needs_marker(entry: BlockReview) -> bool:
    """Every text block (not a figure block), whoever decided it (section 20.11)."""
    return entry.type != BlockType.figure


def tally_markers(reviews: list[ArticleReview]) -> ExportMarkers:
    """The exported blocks by placement and status, from the review sidecars (section 20.11):
    paragraphs carry one marker each, figure blocks none."""
    counts: dict[str, dict[str, int]] = {
        "paragraph": dict.fromkeys(STATUS_WORD, 0),
        "figure": dict.fromkeys(STATUS_WORD, 0),
    }
    for rv in reviews:
        for e in rv.blocks:
            counts[e.placement][e.status] += 1
    return ExportMarkers(
        paragraphs=ArticleReviewCounts(**counts["paragraph"]),
        figures=ArticleReviewCounts(**counts["figure"]),
    )


def encode_reason(reason: str) -> str:
    """The reason as a JSON string that contains no `--`, no `>`, no `<` and no line break, so
    no HTML or CommonMark parser can end the comment early. Decode with `json.loads`."""
    out: list[str] = []
    for ch in json.dumps(reason, ensure_ascii=False):
        if ch == ">":
            out.append("\\u003e")
        elif ch == "<":
            out.append("\\u003c")
        elif ch in _LINE_BREAKS:
            out.append(f"\\u{ord(ch):04x}")
        elif ch == "-" and out and out[-1].endswith("-"):
            out.append("\\u002d")
        else:
            out.append(ch)
    return "".join(out)


def marker_line(entry: BlockReview) -> str:
    if not needs_marker(entry):
        raise ValueError(f"{entry.block_id}: a {entry.status} {entry.type} block has no marker")
    s = f"<!-- ml: {STATUS_WORD[entry.status]}; block: {entry.block_id}"
    if entry.status == "overridden":
        if entry.flag_id is not None:
            s += f"; flag: {entry.flag_id}"
        s += f"; reason: {encode_reason(entry.reason or '')}"
    return s + " -->"


@dataclass(frozen=True)
class Marker:
    status: str  # sidecar spelling: approved | edited | auto_approved | overridden
    block_id: str
    flag_id: str | None
    reason: str | None


def parse_marker(line: str) -> Marker | None:
    """The marker on a whole line, or None when the line is not a well-formed marker."""
    m = MARKER_RE.match(line)
    if m is None:
        return None
    status = _SIDECAR_STATUS[m.group("status")]
    raw = m.group("reason")
    if (raw is not None) != (status == "overridden"):
        return None  # a reason only and always on an override
    if status != "overridden" and m.group("flag") is not None:
        return None
    reason = None
    if raw is not None:
        if "--" in raw or ">" in raw or "<" in raw:
            return None
        try:
            reason = json.loads(raw)
        except ValueError:
            return None
    return Marker(status, m.group("block"), m.group("flag"), reason)


def _tokens(body: str) -> list[Any]:
    from markdown_it import MarkdownIt

    return list(MarkdownIt("commonmark").enable(["table", "strikethrough"]).parse(body))


def _key(line: str) -> str:
    m = MARKER_LIKE_RE.search(line)
    return line[m.start() :] if m else line


def misplaced_markers(body: str) -> list[tuple[str, str]]:
    """(line, what holds it) for every line of `body` containing `<!-- ml:` that is not a whole
    marker line standing as its own top-level HTML block (so a renderer shows nothing). A
    misplaced marker is held by a construct the source text left open (`fence`, `code_block`,
    `html_block`), or sits inside a paragraph, list item or table cell (`inline`). Empty = every
    marker is safe. The same function runs at assembly and in the validator. Lookalikes
    (`MARKER_LIKE_RE`, e.g. `<!--ml:` without the space) are reported too: a marker is exactly
    the grammar of design 11 section 20.2 or it is a problem."""
    own: dict[str, int] = {}
    held: dict[str, str] = {}  # marker fragment -> the first block-level token type holding it
    for t in _tokens(body):  # block-level tokens only; inline children repeat their content
        content = str(t.content or "")
        if not MARKER_LIKE_RE.search(content):
            continue
        line = content.removesuffix("\n")
        if (
            t.type == "html_block"
            and t.level == 0
            and "\n" not in line
            and parse_marker(line) is not None
        ):
            own[line] = own.get(line, 0) + 1
            continue
        for ln in content.split("\n"):
            if MARKER_LIKE_RE.search(ln):
                held.setdefault(_key(ln), t.type)
    out: list[tuple[str, str]] = []
    for ln in body.split("\n"):
        if not MARKER_LIKE_RE.search(ln):
            continue
        if own.get(ln, 0) > 0:
            own[ln] -= 1
            continue
        out.append((ln, held.get(_key(ln), "text")))
    return out
