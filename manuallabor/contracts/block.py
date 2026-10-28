"""Block and its sub-models."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from manuallabor import ids
from manuallabor.contracts._base import (
    BBox,
    BlockId,
    ContractModel,
    DocSlug,
    FigureId,
    Unit,
)
from manuallabor.contracts.enums import (
    BlockStatus,
    BlockType,
    DiffOpKind,
    FaithViolationKind,
    SignalName,
)

__all__ = [
    "BBox",
    "Block",
    "DiffOp",
    "FaithfulnessResult",
    "FaithfulnessViolation",
    "OcrWord",
    "Signal",
    "TableCell",
    "TableData",
    "TableShape",
]


class Signal(ContractModel):
    name: SignalName
    value: Unit
    critical: bool
    detail: str | None = None


class OcrWord(ContractModel):
    text: str
    confidence: Unit
    bbox: BBox | None = None


class TableCell(ContractModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str
    is_header: bool = False


class TableShape(ContractModel):
    rows: int = Field(ge=0)
    cols: int = Field(ge=0)


class TableData(ContractModel):
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: list[TableCell]
    markdown: str
    shape_by_parser: dict[str, TableShape] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_cells(self) -> TableData:
        keys = [(c.row, c.col) for c in self.cells]
        if keys != sorted(keys):
            raise ValueError("cells must be sorted by (row, col)")
        if len(set(keys)) != len(keys):
            raise ValueError("cells must be unique on (row, col)")
        for c in self.cells:
            if c.row + c.row_span > self.n_rows:
                raise ValueError(f"cells: row {c.row}+row_span {c.row_span} exceeds n_rows")
            if c.col + c.col_span > self.n_cols:
                raise ValueError(f"cells: col {c.col}+col_span {c.col_span} exceeds n_cols")
        return self


class DiffOp(ContractModel):
    op: DiffOpKind
    raw: str
    clean: str


class FaithfulnessViolation(ContractModel):
    kind: FaithViolationKind
    raw_start: int | None
    raw_end: int | None
    clean_start: int | None
    clean_end: int | None
    raw: str
    clean: str


class FaithfulnessResult(ContractModel):
    passed: bool
    alignment_ratio: Unit
    violations: list[FaithfulnessViolation]
    diff: list[DiffOp]
    numeric_variant_note: str | None = None

    @model_validator(mode="after")
    def _check_passed(self) -> FaithfulnessResult:
        if self.passed != (self.violations == []):
            raise ValueError("passed must be True exactly when violations is empty")
        return self


class Block(ContractModel):
    id: BlockId
    doc_id: DocSlug
    page: int = Field(ge=1)
    bbox: BBox | None = None
    type: BlockType
    reading_order: int = Field(ge=0)
    raw_text: str
    raw_source: str
    raw_text_by_parser: dict[str, str] = Field(default_factory=dict)
    order_by_parser: dict[str, int] = Field(default_factory=dict)
    clean_text: str | None = None
    confidence: Unit | None = None
    signals: list[Signal] = Field(default_factory=list)
    status: BlockStatus = BlockStatus.queued
    heading_level: int | None = Field(default=None, ge=1, le=6)
    section_number: str | None = Field(default=None, pattern=r"^\d+(\.\d+)*$")
    table: TableData | None = None
    ocr_words: list[OcrWord] | None = None
    numeric_tokens: list[str] = Field(default_factory=list)
    has_numeric_spec: bool = False
    numbers_verified: bool = False
    figure_id: FigureId | None = None
    faithfulness: FaithfulnessResult | None = None

    @field_validator("signals", mode="before")
    @classmethod
    def _sort_signals(cls, v: Any) -> Any:
        if isinstance(v, list):

            def key(s: Any) -> str:
                name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
                return str(getattr(name, "value", name))

            return sorted(v, key=key)
        return v

    @model_validator(mode="after")
    def _check(self) -> Block:
        slug, page, _ = ids.parse_block_id(self.id)
        if slug != self.doc_id or page != self.page:
            raise ValueError("id: slug/page do not match doc_id/page")
        if self.heading_level is not None and self.type != BlockType.heading:
            raise ValueError("heading_level is only allowed when type == heading")
        if self.table is not None and self.type != BlockType.table:
            raise ValueError("table is only allowed when type == table")
        if (self.type == BlockType.figure) != (self.figure_id is not None):
            raise ValueError("figure_id must be set if and only if type == figure")
        if self.figure_id is not None:
            fslug, fpage, _ = ids.parse_figure_id(self.figure_id)
            if fslug != self.doc_id or fpage != self.page:
                raise ValueError("figure_id: slug/page do not match the block")
        names = [s.name for s in self.signals]
        if len(set(names)) != len(names):
            raise ValueError("signals: names must be unique")
        if self.status == BlockStatus.edited and self.clean_text is None:
            raise ValueError("clean_text is required when status == edited")
        return self
