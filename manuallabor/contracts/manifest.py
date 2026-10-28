"""Export manifest."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from manuallabor import ids
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
from manuallabor.contracts.figure import parse_figure_file


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
        if self.id == ids.UNASSIGNED:
            raise ValueError("article id must not be the reserved 'unassigned' marker")
        if ids.parse_article_id(self.id)[0] != self.source_doc:
            raise ValueError("article id must be <source_doc> or <source_doc>--<topic>")
        for bid in self.block_ids:
            if ids.parse_block_id(bid)[0] != self.source_doc:
                raise ValueError(f"article {self.id}: block {bid} belongs to another doc")
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
        if ids.parse_figure_id(self.id)[0] != self.source_doc:
            raise ValueError("figure id slug must equal source_doc")
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
            if a != ids.UNASSIGNED and a not in article_ids:
                raise ValueError(f"accounting.assignments: {b} -> unknown article {a!r}")
        for art in self.articles:
            assigned = {b for b, a in acc.assignments.items() if a == art.id}
            if set(art.block_ids) != assigned:
                raise ValueError(f"articles: {art.id} block_ids do not match accounting")
            if len(set(art.block_ids)) != len(art.block_ids):
                raise ValueError(f"articles: {art.id} has duplicate block_ids")
        unassigned = {b for b, a in acc.assignments.items() if a == ids.UNASSIGNED}
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
                if tgt is None:
                    raise ValueError(
                        f"figures: {f.id} duplicate_of {f.duplicate_of} "
                        "is not a figure in the manifest"
                    )
                if tgt.duplicate_of is not None:
                    raise ValueError(f"figures: {f.id} duplicate_of must point to a root figure")
        for f in self.figures:
            try:
                target = parse_figure_file(f.id, f.file, ("png", "svg"))
            except ValueError as exc:
                raise ValueError(f"figures: {f.id}: {exc}") from exc
            expected = None
            if f.duplicate_of is not None:
                expected = (fig[f.duplicate_of].source_doc, f.duplicate_of)
            if target != expected:
                raise ValueError(f"figures: {f.id} file path disagrees with duplicate_of")
        self._check_docs_and_blocks(fig)
        return self

    def _check_docs_and_blocks(self, fig: dict[str, ManifestFigure]) -> None:
        acc = self.accounting
        slugs = [d.slug for d in self.docs]
        if len(set(slugs)) != len(slugs):
            raise ValueError("docs: slugs must be unique")
        known = set(slugs)
        for art in self.articles:
            if art.source_doc not in known:
                raise ValueError(f"articles: {art.id} source_doc {art.source_doc!r} not in docs")
        for f in fig.values():
            if f.source_doc not in known:
                raise ValueError(f"figures: {f.id} source_doc {f.source_doc!r} not in docs")
        parsed = Counter(b for d in self.docs for b in d.block_ids)
        if acc.total_blocks != sum(parsed.values()):
            raise ValueError("accounting.total_blocks must equal the number of blocks in docs")
        counts = self.review_stats
        status_sum = (
            counts.auto_approved
            + counts.approved
            + counts.edited
            + counts.flagged
            + counts.rejected
            + counts.queued
        )
        if status_sum != counts.total_blocks:
            raise ValueError("review_stats: status counts must sum to total_blocks")
        accounted: Counter[str] = Counter(b for a in self.articles for b in a.block_ids)
        accounted.update(b for b, a in acc.assignments.items() if a == ids.UNASSIGNED)
        missing = sorted((parsed - accounted).elements())
        extra = sorted((accounted - parsed).elements())
        if missing or extra or accounted != parsed:
            raise ValueError(
                f"block accounting: parsed blocks != assigned + unassigned "
                f"(missing={missing[:5]}, extra_or_duplicate={extra[:5]})"
            )
