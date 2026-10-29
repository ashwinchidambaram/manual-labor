"""Internal models and constants for figure extraction (docs/design/02-figures.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from manuallabor.contracts._base import BBox, BlockId, DocSlug, FigureId, PHash, Sha256Hex
from manuallabor.contracts.enums import Extraction

FIGURES_ALGO_VERSION = "1"

VECTOR_MARGIN_PT = 2.0
CROP_MARGIN_PT = 2.0
NATIVE_COVER = 0.90
INSIDE_MIN = 0.98
REL_COVER = 0.05
REL_INSIDE = 0.5
RENDER_MAD_MAX = 3.0
RENDER_P99_MAX = 24.0
RENDER_SIDE = 64
NEAR_DUP_MAX_DIST = 8
ASPECT_TOL = 0.05
BLANK_STD_MIN = 3.0
RENDER_DPI = 300
CAPTION_MAX_GAP_PT = 48.0
EPS = 0.01

Reason = Literal[
    "docx_image",
    "scanned_page",
    "vector_only",
    "vector_crossing_paths",
    "no_content",
    "multiple_images",
    "image_partial_cover",
    "image_with_drawings",
    "image_with_text",
    "image_transform",
    "stencil_mask",
    "smask_size",
    "single_image",
    "render_disagreement",
]
CropSource = Literal["raster", "render"]
DupKind = Literal["exact", "near"]


class FiguresError(Exception):
    """A document's figure stage cannot complete (invariant violation, unreadable input)."""


class FigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


@dataclass(frozen=True)
class Placement:
    bbox: tuple[float, float, float, float]
    transform: tuple[float, float, float, float, float, float]
    xref: int
    width: int
    height: int
    stencil: bool
    smask_dims: tuple[int, int] | None


@dataclass(frozen=True)
class Drawing:
    rect: tuple[float, float, float, float]
    fill: tuple[float, ...] | None
    stroke: tuple[float, ...] | None
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class Span:
    bbox: tuple[float, float, float, float]


@dataclass
class PageContent:
    page_rect: tuple[float, float, float, float]
    has_text_layer: bool
    placements: list[Placement] = field(default_factory=list)
    drawings: list[Drawing] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    method: Extraction
    reason: Reason
    placement: Placement | None = None
    n_relevant: int = 0
    n_ink: int = 0
    cover: float | None = None


class FigureExtraction(FigModel):
    figure_id: FigureId
    block_id: BlockId
    page: int = Field(ge=1)
    bbox: BBox | None
    method: Extraction
    reason: Reason
    crop_source: CropSource | None = None
    source_format: str | None = None
    source_xref: int | None = None
    source_sha256: Sha256Hex | None = None
    bpc: int | None = None
    render_rect: BBox | None = None
    png_sha256: Sha256Hex
    svg_sha256: Sha256Hex | None = None
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    phash: PHash
    blank: bool = False
    effective_dpi: float | None = None
    render_mad: float | None = None
    render_p99: float | None = None
    bbox_area_frac: float | None = None
    caption_block_id: BlockId | None = None
    caption_original: str | None = None
    caption_trimmed: bool = False
    hint_xrefs: list[int] = Field(default_factory=list)
    hint_has_drawings: bool = False


class FigureFailure(FigModel):
    figure_id: FigureId
    block_id: BlockId
    page: int = Field(ge=1)
    reason: str


class FigureReport(FigModel):
    doc_id: DocSlug
    fingerprint: Sha256Hex
    algo_version: str
    figures: list[FigureExtraction]
    failures: list[FigureFailure]


class DedupeEntry(FigModel):
    figure_id: FigureId
    source_doc: DocSlug
    duplicate_of: FigureId | None = None
    kind: DupKind | None = None
    distance: int | None = None


class FigureIndex(FigModel):
    algo_version: str
    near_max_dist: int
    entries: list[DedupeEntry]
