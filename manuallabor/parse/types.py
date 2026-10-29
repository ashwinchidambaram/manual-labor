"""Internal parse-stage models (docs/design/01-parse.md section 2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from manuallabor.contracts._base import BBox, BlockId, Coord, DocSlug, FigureId, Sha256Hex, Unit
from manuallabor.contracts.block import OcrWord, TableCell
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import BlockType, OcrEngine

if TYPE_CHECKING:
    from manuallabor.project import ProjectPaths


class ParseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Line(ParseModel):
    text: str
    bbox: BBox
    size: Coord | None = None
    bold: bool = False
    words: list[OcrWord] = Field(default_factory=list)
    native_id: str


class TableCandidate(ParseModel):
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: list[TableCell]
    header_rows: int = Field(default=0, ge=0)


class RawBlock(ParseModel):
    parser: str
    page: int = Field(ge=1)
    order: int = Field(ge=0)
    bbox: BBox | None = None
    kind: BlockType
    text: str
    lines: list[Line] = Field(default_factory=list)
    size: Coord | None = None
    bold: bool = False
    heading_level: int | None = None
    section_number: str | None = None
    hint: str | None = None
    table: TableCandidate | None = None
    image_xrefs: list[int] = Field(default_factory=list)
    has_drawings: bool = False
    docx_image_rid: str | None = None
    layout_only: bool = False


SkipReason = Literal[
    "empty_text",
    "scan_background",
    "tiny_drawing",
    "table_rule",
    "empty_paragraph",
    "scan_page_region",
]


class Skipped(ParseModel):
    page: int
    order: int
    bbox: BBox | None = None
    reason: SkipReason
    text: str = ""


class PageParse(ParseModel):
    page: int
    width: Coord
    height: Coord
    has_text_layer: bool
    blocks: list[RawBlock]
    skipped: list[Skipped] = Field(default_factory=list)


class ParserOutput(ParseModel):
    parser: str
    version: str
    source_sha256: Sha256Hex
    pages: list[PageParse]


class OcrPage(ParseModel):
    page: int
    engine: OcrEngine
    dpi: int
    width: Coord
    height: Coord
    lines: list[Line]


class OcrOutput(ParseModel):
    role: Literal["ocr", "ocr_alt"]
    engine: OcrEngine
    version: str
    source_sha256: Sha256Hex
    pages: list[OcrPage]


class Disposition(ParseModel):
    parser: str
    page: int
    order: int
    outcome: Literal["primary", "matched", "split", "aligned", "absorbed", "alone", "skipped"]
    block_id: BlockId | None = None
    detail: str | None = None


class MergeReport(ParseModel):
    doc_id: DocSlug
    dispositions: list[Disposition]


class Band(ParseModel):
    y0: Coord
    y1: Coord
    columns: list[list[Coord]]


class Overlap(ParseModel):
    a: BlockId
    b: BlockId
    iou: Unit


class PageLayout(ParseModel):
    page: int
    source: Literal["textlayer", "ocr", "docx"]
    n_columns: int
    bands: list[Band]
    block_columns: dict[BlockId, int]
    overlaps: list[Overlap]


class FigureCandidate(ParseModel):
    figure_id: FigureId
    block_id: BlockId
    page: int
    bbox: BBox | None = None
    sources: list[str]
    image_xrefs: list[int]
    has_drawings: bool
    docx_image_rid: str | None = None


class ParseState(ParseModel):
    sha256: Sha256Hex
    parser_versions: dict[str, str]
    config_fingerprint: Sha256Hex
    stages_done: list[str]
    complete: bool


class ParseError(Exception):
    """A document cannot be parsed (contract violation, unsupported input, ...)."""


class ParserUnavailable(ParseError):
    """A required parser cannot run here (for example, Docling models are not cached)."""


@dataclass(frozen=True)
class ParseContext:
    slug: str
    sha256: str
    page_sizes: tuple[tuple[float, float], ...]
    text_layer: tuple[bool, ...]
    config: ProjectConfig
    paths: ProjectPaths


class PdfParserAdapter(Protocol):
    name: str

    def version(self) -> str: ...

    def parse_pdf(self, path: Path, ctx: ParseContext) -> ParserOutput: ...
