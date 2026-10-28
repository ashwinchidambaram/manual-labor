"""Structure and topic groups."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from manuallabor import ids
from manuallabor.contracts._base import (
    BlockId,
    ContractModel,
    DocSlug,
    GroupId,
    TopicSlug,
    Unit,
)
from manuallabor.contracts.enums import GroupView


class PageRange(ContractModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self) -> PageRange:
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class Group(ContractModel):
    id: GroupId
    view: GroupView
    doc_id: DocSlug
    title: str = Field(min_length=1)
    slug: TopicSlug
    block_ids: list[BlockId]
    page_ranges: list[PageRange]
    section_ids: list[GroupId] = Field(default_factory=list)
    parent_id: GroupId | None = None
    level: int = Field(default=0, ge=0)
    section_number: str | None = None
    cohesion: Unit | None = None
    is_unassigned: bool = False
    block_count: int = Field(ge=0)
    figure_count: int = Field(ge=0)

    @field_validator("section_ids", mode="before")
    @classmethod
    def _sort_sections(cls, v: Any) -> Any:
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return sorted(v)
        return v

    @model_validator(mode="after")
    def _check(self) -> Group:
        m = ids.GROUP_ID_RE.match(self.id)
        if m is None:
            raise ValueError("id: not a group id")
        letter = m.group("view")
        if (letter == "s") != (self.view == GroupView.structure):
            raise ValueError("view does not match the id letter")
        if m.group("slug") != self.doc_id:
            raise ValueError("id: slug does not match doc_id")
        if self.block_count != len(self.block_ids):
            raise ValueError("block_count must equal len(block_ids)")
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("block_ids must be unique")
        for b in self.block_ids:
            if ids.parse_block_id(b)[0] != self.doc_id:
                raise ValueError("block_ids: all blocks must come from doc_id")
        if self.is_unassigned and not (
            self.view == GroupView.topic
            and re.search(r"-t000$", self.id)
            and self.slug == "unassigned"
        ):
            raise ValueError("is_unassigned requires a topic view, id t000 and slug 'unassigned'")
        if self.parent_id is not None and self.view != GroupView.structure:
            raise ValueError("parent_id requires view == structure")
        prev_end = 0
        for r in self.page_ranges:
            if r.start <= prev_end:
                raise ValueError("page_ranges must be sorted and non-overlapping")
            prev_end = r.end
        return self


Topic = Group
