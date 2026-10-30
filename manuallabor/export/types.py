"""Internal types of the export package (design 11 section 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from manuallabor.cleanup.types import AttachFile
from manuallabor.contracts.article import ArticleFrontmatter
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import ArticleSplit
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.manifest import Manifest, ManifestLearning
from manuallabor.state.models import ExportReviewSummary

EXPORT_ALGO_VERSION: Final = "1"
MAX_ARTICLE_BYTES: Final = 500_000
BLOCKER_LIMIT: Final = 20
NO_CAPTION: Final = "(no caption)"
GENERATED_PREFIX: Final = "[generated] "


class ExportError(Exception):
    """The export cannot proceed (stale input, unreadable figure, failed validation)."""


class GateLocked(ExportError):
    """The export gate is closed: open flags or queued in-scope blocks without an override."""

    def __init__(self, open_flags: int, queued: int, blockers: list[str]) -> None:
        self.open_flags = open_flags
        self.queued = queued
        self.blockers = blockers
        shown = ", ".join(blockers[:BLOCKER_LIMIT])
        more = f" (+{len(blockers) - BLOCKER_LIMIT} more)" if len(blockers) > BLOCKER_LIMIT else ""
        super().__init__(
            f"export is locked: {open_flags} open flag(s), {queued} queued block(s); "
            f"{len(blockers)} blocker(s): {shown}{more}"
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


@dataclass
class DocInput:
    doc: Document
    blocks: list[Block]  # review overlay, parse order
    groups: GroupsFile
    attach: AttachFile
    figures: dict[str, FigureData]
    selected: set[str]
    scope: set[str]  # selected blocks + figure blocks attached to an article


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


@dataclass(frozen=True)
class BodyPart:
    kind: Literal["block", "figure"]
    block_id: str | None  # the source block of a "block" part
    figure_id: str | None
    text: str


@dataclass
class BuiltArticle:
    id: str
    path: str
    text: str
    frontmatter: ArticleFrontmatter
    title: str
    block_ids: list[str]
    figure_ids: list[str]
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
