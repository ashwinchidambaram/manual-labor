"""Article front matter (SPEC 6.2)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from manuallabor.contracts._base import ArticleId, ContractModel, DocSlug, FigureId, UTCDateTime


class ReviewCounts(ContractModel):
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    overrides: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ReviewCounts:
        if self.edited > self.approved:
            raise ValueError("review.edited must be <= review.approved")
        return self


class ArticleFrontmatter(ContractModel):
    id: ArticleId
    title: str
    source_doc: DocSlug
    source_file: str
    product_model: str | None
    pages: list[int]
    sections: list[str]
    figures: list[FigureId]
    blocks: int = Field(ge=0)
    review: ReviewCounts
    generated_at: UTCDateTime

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, v: list[int]) -> list[int]:
        if v != sorted(set(v)) or any(p < 1 for p in v):
            raise ValueError("pages must be sorted, unique and >= 1")
        return v

    @model_validator(mode="after")
    def _check(self) -> ArticleFrontmatter:
        if self.review.approved > self.blocks:
            raise ValueError("review.approved must be <= blocks")
        if self.id != self.source_doc and not self.id.startswith(f"{self.source_doc}--"):
            raise ValueError("id must equal source_doc or start with '<source_doc>--'")
        if len(set(self.figures)) != len(self.figures):
            raise ValueError("figures must be unique")
        return self

    def to_yaml_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
