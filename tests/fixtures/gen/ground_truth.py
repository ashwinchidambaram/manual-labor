"""Ground-truth models for the fixtures (test-only, not exported as schemas)."""

from __future__ import annotations

from manuallabor.contracts._base import ContractModel
from manuallabor.contracts.block import BBox, TableCell
from manuallabor.contracts.enums import BlockType, DocKind, Extraction


class GTSourceImage(ContractModel):
    sha256: str
    width: int
    height: int


class GTTable(ContractModel):
    n_rows: int
    n_cols: int
    cells: list[TableCell]
    bordered: bool
    has_merged: bool
    ragged: bool
    caption: str | None


class GTBlock(ContractModel):
    index: int
    page: int
    type: BlockType
    text: str
    raw_lines: list[str]
    bbox: BBox | None
    heading_level: int | None = None
    section_number: str | None = None
    column: int | None = None
    is_header_footer: bool = False
    numeric_tokens: list[str]
    numeric_specs: list[str]
    has_numeric_spec: bool
    hyphenated: bool = False
    figure_refs: list[int]
    table: GTTable | None = None


class GTFigure(ContractModel):
    number: int | None
    expected_id: str
    page: int
    bbox: BBox | None
    expected_extraction: Extraction
    caption: str | None
    caption_block_index: int | None
    referenced_by: list[int]
    duplicate_of: str | None
    near_duplicate: bool
    source_image: GTSourceImage | None
    section_number: str | None


class GroundTruth(ContractModel):
    fixture: str
    file: str
    sha256: str
    kind: DocKind
    page_count: int
    page_size: list[float] | None
    expected_slug: str
    title: str
    product_model: str
    header_text: str | None
    footer_template: str | None
    derived_from: str | None
    text_is_reference: bool
    blocks: list[GTBlock]
    figures: list[GTFigure]
