"""Export manifest."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from manuallabor.contracts._base import (
    ArticleId,
    BlockId,
    ContractModel,
    DocSlug,
    FigureId,
    FlagId,
    TargetId,
    Unit,
    UTCDateTime,
)
from manuallabor.contracts.config import ModelRef
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import ArticleSplit, Task


def _sorted_by(key: str, v: Any) -> Any:
    if isinstance(v, list):

        def k(x: Any) -> str:
            return str(x.get(key) if isinstance(x, dict) else getattr(x, key, ""))

        return sorted(v, key=k)
    return v


class ManifestProject(ContractModel):
    name: str
    tool_version: str
    generated_at: UTCDateTime


class ManifestArticle(ContractModel):
    id: ArticleId
    path: str
    title: str
    source_doc: DocSlug
    block_ids: list[BlockId]
    figures: list[FigureId]
    pages: list[int]
    sections: list[str]

    @model_validator(mode="after")
    def _check(self) -> ManifestArticle:
        if self.path != f"articles/{self.id}.md":
            raise ValueError("path must be articles/<id>.md")
        return self


class ManifestFigure(ContractModel):
    id: FigureId
    sidecar: str
    file: str
    source_doc: DocSlug
    duplicate_of: FigureId | None = None

    @model_validator(mode="after")
    def _check(self) -> ManifestFigure:
        if self.sidecar != f"images/{self.source_doc}/{self.id}.json":
            raise ValueError("sidecar must be images/<source_doc>/<id>.json")
        return self


class ReviewStats(ContractModel):
    total_blocks: int = Field(ge=0)
    auto_approved: int = Field(ge=0)
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    flagged: int = Field(ge=0)
    rejected: int = Field(ge=0)
    queued: int = Field(ge=0)
    overrides: int = Field(ge=0)
    numbers_verified_blocks: list[BlockId]

    @field_validator("numbers_verified_blocks", mode="before")
    @classmethod
    def _sort(cls, v: Any) -> Any:
        return sorted(v) if isinstance(v, list) else v


class Override(ContractModel):
    target_id: TargetId | None = None
    flag_id: FlagId | None = None
    reason: str
    at: UTCDateTime


class BlockAccounting(ContractModel):
    total_blocks: int = Field(ge=0)
    assignments: dict[BlockId, str]
    unassigned_reasons: dict[BlockId, Literal["not_selected", "header_footer", "rejected", "empty"]]


class Manifest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    project: ManifestProject
    docs: list[Document]
    articles: list[ManifestArticle]
    figures: list[ManifestFigure]
    review_stats: ReviewStats
    models: dict[Task, ModelRef]
    threshold: Unit
    article_split: ArticleSplit
    overrides: list[Override]
    accounting: BlockAccounting

    @field_validator("docs", mode="before")
    @classmethod
    def _sort_docs(cls, v: Any) -> Any:
        return _sorted_by("slug", v)

    @field_validator("articles", "figures", mode="before")
    @classmethod
    def _sort_id(cls, v: Any) -> Any:
        return _sorted_by("id", v)

    @model_validator(mode="after")
    def _check(self) -> Manifest:
        acc = self.accounting
        if acc.total_blocks != len(acc.assignments):
            raise ValueError("accounting.total_blocks must equal len(assignments)")
        if acc.total_blocks != self.review_stats.total_blocks:
            raise ValueError("accounting.total_blocks must equal review_stats.total_blocks")
        article_ids = {a.id for a in self.articles}
        for b, a in acc.assignments.items():
            if a != "unassigned" and a not in article_ids:
                raise ValueError(f"accounting.assignments: {b} -> unknown article {a!r}")
        for art in self.articles:
            assigned = {b for b, a in acc.assignments.items() if a == art.id}
            if set(art.block_ids) != assigned:
                raise ValueError(f"articles: {art.id} block_ids do not match accounting")
            if len(set(art.block_ids)) != len(art.block_ids):
                raise ValueError(f"articles: {art.id} has duplicate block_ids")
        unassigned = {b for b, a in acc.assignments.items() if a == "unassigned"}
        if set(acc.unassigned_reasons) != unassigned:
            raise ValueError("accounting.unassigned_reasons keys must be exactly unassigned blocks")
        fig = {f.id: f for f in self.figures}
        for art in self.articles:
            for fid in art.figures:
                if fid not in fig:
                    raise ValueError(f"articles: {art.id} references unknown figure {fid}")
        for f in self.figures:
            if f.duplicate_of is not None:
                tgt = fig.get(f.duplicate_of)
                if tgt is None or tgt.duplicate_of is not None:
                    raise ValueError(f"figures: {f.id} duplicate_of must point to a root figure")
        return self
