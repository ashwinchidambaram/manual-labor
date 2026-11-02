"""Internal types of the export package (design 11 section 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from manuallabor.cleanup.types import AttachFile
from manuallabor.contracts.article import ArticleFrontmatter, ArticleReview
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import ArticleSplit
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.manifest import ExportMarks, Manifest, ManifestLearning
from manuallabor.state.models import ExportReviewSummary

# 2: review markers and sidecars (section 20); 3: a marker before every paragraph, front matter
# counts in the sidecar's categories, sidecar `text` and `placement` (section 20.11); 4: the
# original text of edited blocks, figure-line markers, reason references and the visible marks
# option (sections 20.12 to 20.15)
EXPORT_ALGO_VERSION: Final = "4"
MAX_ARTICLE_BYTES: Final = 500_000
BLOCKER_LIMIT: Final = 20
NO_CAPTION: Final = "(no caption)"
GENERATED_PREFIX: Final = "[generated] "


class ExportError(Exception):
    """The export cannot proceed (stale input, unreadable figure, failed validation)."""


class GateLocked(ExportError):
    """The export gate is closed: open flags or queued in-scope blocks without an override."""

    def __init__(
        self,
        open_flags: int,
        queued: int,
        blockers: list[str],
        faith_failed: list[str] | None = None,
    ) -> None:
        self.open_flags = open_flags
        self.queued = queued
        self.blockers = blockers
        self.faith_failed = list(faith_failed or [])
        shown = ", ".join(blockers[:BLOCKER_LIMIT])
        more = f" (+{len(blockers) - BLOCKER_LIMIT} more)" if len(blockers) > BLOCKER_LIMIT else ""
        why = ""
        if self.faith_failed:
            # design 11 section 20.16: said by name, because no override can lift these
            ff = ", ".join(self.faith_failed[:BLOCKER_LIMIT])
            why = (
                f"; {len(self.faith_failed)} block(s) where cleanup changed the text (the "
                f"faithfulness check failed) need a person, no override covers them: {ff}; "
                "approve each after reading the change, edit it or reject it in Verify"
            )
        super().__init__(
            f"export is locked: {open_flags} open flag(s), {queued} queued block(s); "
            f"{len(blockers)} blocker(s): {shown}{more}{why}"
        )


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code} {self.where}: {self.detail}"


@dataclass(frozen=True)
class ActiveOverride:
    """An `export_override` action that applies to the next export (design P3)."""

    action_id: int
    ts: datetime
    reason: str
    target_id: str | None
    flag_id: str | None


@dataclass
class FigureData:
    """One figure of a document: its sidecar, extraction facts and the files behind it."""

    record: FigureRecord
    caption_block_id: str | None
    canonical: str | None  # the root figure id when this figure is a duplicate
    png: Path  # the file `record.file` resolves to (the canonical's own for a duplicate)
    svg: Path | None


@dataclass(frozen=True)
class HumanDecision:
    """The decision that gives an approved or edited block its status (design 11 section 20)."""

    at: datetime  # the effective decision's timestamp
    edited_by: Literal["person", "agent_proposal"] | None  # for an edited block: who wrote it
    # for an edited block (section 20.12): when the effective edit was made, and the raw text it
    # replaced (the block's `raw_text`, proven by the edit decision's `raw_sha256`)
    edited_at: datetime | None = None
    original_text: str | None = None


@dataclass
class DocInput:
    doc: Document
    blocks: list[Block]  # review overlay, parse order
    groups: GroupsFile
    attach: AttachFile
    figures: dict[str, FigureData]
    selected: set[str]
    scope: set[str]  # selected blocks + figure blocks attached to an article
    # block id -> the person's decision, for every approved or edited block (section 20)
    decisions: dict[str, HumanDecision] = field(default_factory=dict)


@dataclass
class AssembleInputs:
    config: ProjectConfig
    split: ArticleSplit
    docs: dict[str, DocInput]
    flags: list[Flag]
    overrides: list[ActiveOverride]
    models: dict[str, tuple[str, str]]  # task -> (provider, model)
    learning: ManifestLearning
    tool_version: str
    marks: ExportMarks = "invisible"  # visible review tags too (section 20.15)


@dataclass(frozen=True)
class BodyPart:
    kind: Literal["block", "figure"]
    block_id: str | None  # the source block of a "block" part
    figure_id: str | None
    text: str  # the block's part as rendered (what `text_sha256` hashes), or the figure line
    marker: str | None = None  # the part's review marker (design 11 sections 20.11, 20.13)
    tag: str | None = None  # its visible review tag, `--marks visible` only (section 20.15)

    @property
    def unit(self) -> str:
        """What the article holds: the marker line directly above the part, and in a visible
        export the tag paragraph above the marker of a paragraph nobody checked."""
        u = self.text if self.marker is None else self.marker + "\n" + self.text
        return u if self.tag is None else self.tag + "\n\n" + u


@dataclass
class BuiltArticle:
    id: str
    path: str
    text: str
    frontmatter: ArticleFrontmatter
    title: str
    block_ids: list[str]
    figure_ids: list[str]
    review: ArticleReview  # the sidecar, articles/<id>.review.json (section 20)
    review_path: str
    body_parts: list[BodyPart] = field(default_factory=list)


@dataclass
class BuiltFigure:
    id: str
    sidecar_path: str  # images/<slug>/<id>.json
    sidecar: FigureRecord
    canonical: str | None
    png: Path | None  # None for a duplicate (its file is the canonical's)
    png_path: str | None
    svg: Path | None
    svg_path: str | None


@dataclass
class Assembled:
    articles: list[BuiltArticle]
    figures: list[BuiltFigure]
    manifest: Manifest
    readme: str
    pages_covered: int
    warnings: list[str]
    generated_at: datetime
    review: ExportReviewSummary  # the exported blocks, one bucket each (design 11 section 14)
    # zip path -> text (str) or a file on disk (Path); sorted by path when written
    files: dict[str, str | Path] = field(default_factory=dict)
