"""User selection of blocks, and the coverage / scope numbers derived from it."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from manuallabor import ids
from manuallabor.contracts._base import BlockId, ContractModel, DocSlug, GroupId, Unit
from manuallabor.contracts.enums import ArticleSplit, GroupView


class Selection(ContractModel):
    block_ids: list[BlockId]
    article_split: ArticleSplit = ArticleSplit.per_topic
    active_view: GroupView = GroupView.topic
    # Documents that were grouped when the selection was last written (design 08 section 10).
    # A grouped document missing from this list arrived later and enters fully selected, the
    # same as every document on a fresh project. None: a selection saved before this field
    # existed, read as exactly the blocks it lists.
    known_docs: list[DocSlug] | None = None

    @field_validator("block_ids", mode="before")
    @classmethod
    def _dedupe_sort(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple, set, frozenset)) and all(isinstance(x, str) for x in v):
            try:
                return sorted(set(v), key=ids.block_sort_key)
            except ValueError:
                return list(v)
        return v

    @field_validator("known_docs", mode="before")
    @classmethod
    def _sorted_docs(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple, set, frozenset)) and all(isinstance(x, str) for x in v):
            return sorted(set(v))
        return v


class GroupCoverage(ContractModel):
    group_id: GroupId
    view: GroupView
    selected: int = Field(ge=0)
    total: int = Field(ge=0)
    fraction: Unit | None
    subtree_selected: int | None = Field(ge=0)
    subtree_total: int | None = Field(ge=0)
    subtree_fraction: Unit | None


class CoverageReport(ContractModel):
    doc_id: DocSlug
    selected: int = Field(ge=0)
    selectable: int = Field(ge=0)
    structure: list[GroupCoverage]
    topics: list[GroupCoverage]


class ReviewLoad(ContractModel):
    queued: int = Field(ge=0)
    numeric_queued: int = Field(ge=0)
    threshold: Unit


class ScopeSummary(ContractModel):
    docs: int = Field(ge=0)
    articles_per_topic: int = Field(ge=0)
    articles_per_document: int = Field(ge=0)
    articles: int = Field(ge=0)
    blocks: int = Field(ge=0)
    figures: int = Field(ge=0)
    pages: int = Field(ge=0)
    review_load: ReviewLoad
