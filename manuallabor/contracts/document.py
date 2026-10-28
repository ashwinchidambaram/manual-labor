"""Document record."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from manuallabor.contracts._base import ContractModel, DocSlug, Sha256Hex
from manuallabor.contracts.enums import DocKind


class Document(ContractModel):
    slug: DocSlug
    sha256: Sha256Hex
    filename: str = Field(min_length=1)
    title: str | None = None
    product_model: str | None = None
    product_model_inferred: bool = False
    kind: DocKind
    page_count: int = Field(ge=1)
    pages_without_text_layer: list[int] = Field(default_factory=list)
    stripped_headers: list[str] = Field(default_factory=list)
    stripped_footers: list[str] = Field(default_factory=list)
    parser_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("filename")
    @classmethod
    def _basename(cls, v: str) -> str:
        if "/" in v or "\\" in v:
            raise ValueError("filename must be a basename")
        return v

    @field_validator("pages_without_text_layer", mode="before")
    @classmethod
    def _sorted_pages(cls, v: Any) -> Any:
        return v

    @field_validator("pages_without_text_layer")
    @classmethod
    def _check_pages(cls, v: list[int]) -> list[int]:
        if v != sorted(set(v)):
            raise ValueError("pages_without_text_layer must be sorted and unique")
        return v

    @field_validator("stripped_headers", "stripped_footers")
    @classmethod
    def _check_sorted_str(cls, v: list[str]) -> list[str]:
        if v != sorted(set(v)):
            raise ValueError("entries must be sorted and unique")
        return v

    @model_validator(mode="after")
    def _check(self) -> Document:
        if self.product_model_inferred and self.product_model is None:
            raise ValueError("product_model_inferred requires product_model")
        if any(p < 1 or p > self.page_count for p in self.pages_without_text_layer):
            raise ValueError("pages_without_text_layer: pages must be within 1..page_count")
        if self.kind == DocKind.docx and self.pages_without_text_layer:
            raise ValueError("pages_without_text_layer must be empty for docx")
        return self
