"""Review markers (design 11 sections 20, 20.11 and 20.13 to 20.15). Pure.

A marker is an HTML comment on a line of its own, the first line of every exported unit: a
blank line above it, its paragraph or figure line directly below it. Every text block has one,
whatever its status (approved, edited, auto-approved, overridden), and so does every figure
line (auto-approved, approved, overridden: who decided to show the figure there). An override's
reason is a reference `r<n>` into the article's review file. Renderers show nothing;
`grep '^<!-- ml: '` lists the units; the id leads to the review sidecar. With `--marks visible`
a paragraph nobody checked also has a short visible tag paragraph above its marker.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from manuallabor.contracts.article import (
    ArticleReview,
    ArticleReviewCounts,
    BlockReview,
    FigureLineReview,
)
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.manifest import ExportMarks
from manuallabor.state.models import ExportMarkers

__all__ = [
    "MARKER_LIKE_RE",
    "MARKER_PREFIX",
    "MARKER_RE",
    "SOURCE_MARKER_RE",
    "STATUS_WORD",
    "TAG",
    "Marker",
    "marker_line",
    "misplaced_markers",
    "needs_marker",
    "parse_marker",
    "strip_visible_marks",
    "tag_link_labels",
    "tag_of",
    "tally_markers",
]

MARKER_PREFIX: Final = "<!-- ml:"
# anything a reader or a grep could take for a marker: an HTML comment opening that starts with
# "ml:", spacing and case aside. An odd run of backslashes before `<` makes it literal text
# (CommonMark punctuation escape), which is how alt text carries a `<`; an even run does not.
MARKER_LIKE_RE: Final = re.compile(r"(?<!\\)(?:\\\\)*<!--\s*ml\s*:", re.IGNORECASE)
# the same in source text, backslashes or not: block text and titles holding it are refused
SOURCE_MARKER_RE: Final = re.compile(r"<!--\s*ml\s*:", re.IGNORECASE)
_BLOCK_OR_FIGURE: Final = r"b-[a-z0-9-]+-p\d{3,}-\d{2,}|FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}"
MARKER_RE: Final = re.compile(
    r"^<!-- ml: (?P<status>approved|edited|auto-approved|overridden); block: "
    rf"(?P<block>{_BLOCK_OR_FIGURE})"
    r"(?:; flag: (?P<flag>flag-\d{6}))?"
    r"(?:; reason: (?P<reason>r[1-9][0-9]*))? -->$"
)
STATUS_WORD: Final = {
    "approved": "approved",
    "edited": "edited",
    "auto_approved": "auto-approved",
    "overridden": "overridden",
}
_SIDECAR_STATUS: Final = {w: s for s, w in STATUS_WORD.items()}
# section 20.15: the visible tag of a paragraph nobody checked (none for a person's decision)
TAG: Final = {"auto_approved": "[unchecked]", "overridden": "[overridden]"}
_STRIP_RE: Final = re.compile(
    r"\n\n(?:\[unchecked\]\n\n(?=<!-- ml: auto-approved; block: b-)"
    r"|\[overridden\]\n\n(?=<!-- ml: overridden; block: b-))"
)


def needs_marker(entry: BlockReview) -> bool:
    """Every text block (not a figure block), whoever decided it (section 20.11). A figure
    block's figure lines carry their own markers (section 20.13)."""
    return entry.type != BlockType.figure


def tag_of(entry: BlockReview, marks: ExportMarks) -> str | None:
    """The visible tag above a paragraph's marker (section 20.15): only in a visible export, only
    on a paragraph nobody checked."""
    if marks != "visible" or not needs_marker(entry):
        return None
    return TAG.get(entry.status)


def tag_link_labels(text: str) -> list[str]:
    """The tags a CommonMark link reference definition in `text` would turn into links, as the
    parser itself collects them (definitions inside block quotes and list items apply to the
    whole document, and labels are case- and space-normalized), e.g. `["[unchecked]"]`."""
    from markdown_it import MarkdownIt

    env: dict[str, Any] = {}
    MarkdownIt("commonmark").parse(text, env)
    refs = env.get("references", {})
    return [t for t in TAG.values() if t[1:-1].upper() in refs]


def strip_visible_marks(text: str, marks: ExportMarks) -> str:
    """The article without its visible tags (section 20.15 c), for every comparison of article
    text with the source: each `"\n\n" + tag + "\n\n"` directly before a paragraph marker of the
    matching status becomes `"\n\n"`. Identity on an invisible export. Never removes source
    text: in a visible export the line directly before `"\n\n"` + such a marker is always its
    tag, because source text cannot hold a marker (section 20.6)."""
    if marks != "visible":
        return text
    return _STRIP_RE.sub("\n\n", text)


def tally_markers(reviews: Sequence[ArticleReview]) -> ExportMarkers:
    """The exported blocks by placement and status, from the review sidecars (section 20.11):
    paragraphs carry one marker each; figure blocks are counted as blocks; figure lines carry
    one marker each, by the status of their placement (section 20.13)."""
    counts: dict[str, dict[str, int]] = {
        "paragraph": dict.fromkeys(STATUS_WORD, 0),
        "figure": dict.fromkeys(STATUS_WORD, 0),
        "line": dict.fromkeys(STATUS_WORD, 0),
    }
    for rv in reviews:
        for e in rv.blocks:
            counts[e.placement][e.status] += 1
        for fl in rv.figure_lines:
            counts["line"][fl.status] += 1
    return ExportMarkers(
        paragraphs=ArticleReviewCounts(**counts["paragraph"]),
        figures=ArticleReviewCounts(**counts["figure"]),
        figure_lines=ArticleReviewCounts(**counts["line"]),
    )


def marker_line(entry: BlockReview | FigureLineReview) -> str:
    """`<!-- ml: <status>; block: <id>[; flag: <flag>][; reason: r<n>] -->`: the block id of a
    paragraph, the figure id of a figure line."""
    if isinstance(entry, BlockReview):
        if not needs_marker(entry):
            raise ValueError(f"{entry.block_id}: a figure block has no marker of its own")
        ident = entry.block_id
    else:
        ident = entry.figure_id
    s = f"<!-- ml: {STATUS_WORD[entry.status]}; block: {ident}"
    if entry.status == "overridden":
        if entry.reason_id is None:
            raise ValueError(f"{ident}: an overridden entry needs its reason id")
        if entry.flag_id is not None:
            s += f"; flag: {entry.flag_id}"
        s += f"; reason: {entry.reason_id}"
    return s + " -->"


@dataclass(frozen=True)
class Marker:
    status: str  # sidecar spelling: approved | edited | auto_approved | overridden
    block_id: str  # a block id, or a figure id for a figure line's marker
    flag_id: str | None
    reason_id: str | None

    @property
    def is_figure(self) -> bool:
        return self.block_id.startswith("FIG-")


def parse_marker(line: str) -> Marker | None:
    """The marker on a whole line, or None when the line is not a well-formed marker."""
    m = MARKER_RE.match(line)
    if m is None:
        return None
    status = _SIDECAR_STATUS[m.group("status")]
    reason = m.group("reason")
    if (reason is not None) != (status == "overridden"):
        return None  # a reason only and always on an override
    if status != "overridden" and m.group("flag") is not None:
        return None
    if m.group("block").startswith("FIG-") and status == "edited":
        return None  # a figure line is never edited
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
