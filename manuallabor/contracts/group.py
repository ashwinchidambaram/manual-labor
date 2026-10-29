"""Structure and topic groups."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from manuallabor import ids
from manuallabor.contracts._base import (
    BlockId,
    ContractModel,
    DocSlug,
    GroupId,
    Sha256Hex,
    TopicSlug,
    Unit,
    round6,
)
from manuallabor.contracts.enums import GroupView, TitleSource, UnassignedReason


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


class UnassignedEntry(ContractModel):
    block_id: BlockId
    view: GroupView
    reason: UnassignedReason


class GroupOverlap(ContractModel):
    topic_id: GroupId
    section_id: GroupId
    blocks: int = Field(ge=1)


Similarity = Annotated[float, Field(ge=-1.0, le=1.0, allow_inf_nan=False), AfterValidator(round6)]


class StragglerRecord(ContractModel):
    block_id: BlockId
    topic_id: GroupId | None
    similarity: Similarity
    by: Literal["centroid", "llm"]


class GroupingParams(ContractModel):
    """Every grouping constant, frozen into groups.json so a result can be explained."""

    summary_tokens: int = Field(ge=1)
    name_sample: int = Field(ge=1)
    name_tokens: int = Field(ge=1)
    embed_batch: int = Field(ge=1)
    embed_prefix: str
    small_doc: int = Field(ge=0)
    d_cut: float = Field(ge=0.0, allow_inf_nan=False)
    k_max_divisor: int = Field(ge=1)
    min_topic_blocks: int = Field(ge=1)
    max_topic_blocks: int = Field(ge=2)
    t_assign: float = Field(allow_inf_nan=False)
    t_candidate: float = Field(allow_inf_nan=False)
    n_candidates: int = Field(ge=1)
    straggler_batch: int = Field(ge=1)
    low_cohesion: Unit
    page_window: int = Field(ge=1)
    title_max: int = Field(ge=1)
    topic_slug_max: int = Field(ge=1)
    llm_stragglers: bool


class GroupOverride(ContractModel):
    """A human regrouping decision, appended to docs/<slug>/group_overrides.json."""

    seq: int = Field(ge=1)
    kind: Literal["move", "rename"]
    block_id: BlockId | None = None
    to_topic_slug: TopicSlug | None = None
    title: str | None = None
    topic_slug: TopicSlug | None = None

    @model_validator(mode="after")
    def _check(self) -> GroupOverride:
        if self.kind == "move":
            if self.block_id is None or self.to_topic_slug is None:
                raise ValueError("move requires block_id and to_topic_slug")
        elif self.topic_slug is None or self.title is None:
            raise ValueError("rename requires topic_slug and title")
        return self


class GroupsFile(ContractModel):
    """docs/<slug>/groups.json: both views of one document, the accounting of blocks that sit in
    no group, and the provenance needed to explain or reproduce the result."""

    doc_id: DocSlug
    algo_version: str
    fingerprint: Sha256Hex
    embedding_model: str
    embedding_dim: int = Field(ge=0)
    grouping_model: str
    learning_snapshot: str
    params: GroupingParams
    structure: list[Group]
    topics: list[Group]
    unassigned: list[UnassignedEntry]
    stragglers: list[StragglerRecord]
    overlap: list[GroupOverlap]
    title_sources: dict[GroupId, TitleSource]
    topic_status: Literal["ok", "failed"]
    topic_error: str | None = None
    overrides_applied: int = Field(ge=0)
    overrides_stale: list[int]

    @model_validator(mode="after")
    def _check(self) -> GroupsFile:
        for name, groups, view in (
            ("structure", self.structure, GroupView.structure),
            ("topics", self.topics, GroupView.topic),
        ):
            seen: set[str] = set()
            for g in groups:
                if g.view != view or g.doc_id != self.doc_id:
                    raise ValueError(f"{name}: group {g.id} has the wrong view or doc")
                for b in g.block_ids:
                    if b in seen:
                        raise ValueError(f"{name}: block {b} is in more than one group")
                    seen.add(b)
        by_view: dict[GroupView, set[str]] = {GroupView.structure: set(), GroupView.topic: set()}
        for u in self.unassigned:
            if u.block_id in by_view[u.view]:
                raise ValueError(f"unassigned: {u.block_id} listed twice in view {u.view}")
            by_view[u.view].add(u.block_id)
            if u.view == GroupView.structure and u.reason != UnassignedReason.header_footer:
                raise ValueError("unassigned: structure-view entries must be header_footer")
        t000 = [g for g in self.topics if g.is_unassigned]
        if len(t000) > 1:
            raise ValueError("topics: more than one unassigned group")
        expected = [
            u.block_id
            for u in self.unassigned
            if u.view == GroupView.topic and u.reason != UnassignedReason.header_footer
        ]
        got = t000[0].block_ids if t000 else []
        if got != expected:
            raise ValueError("t000 block_ids must equal the non-header/footer topic-view entries")
        if self.topic_status == "failed" and self.topic_error is None:
            raise ValueError("topic_error is required when topic_status == failed")
        if self.topic_status == "ok" and self.topic_error is not None:
            raise ValueError("topic_error requires topic_status == failed")
        sec_of = {b: g.id for g in self.structure for b in g.block_ids}
        counts: dict[tuple[str, str], int] = {}
        for t in self.topics:
            for b in t.block_ids:
                s = sec_of.get(b)
                if s is not None:
                    counts[(t.id, s)] = counts.get((t.id, s), 0) + 1
        listed = {(o.topic_id, o.section_id): o.blocks for o in self.overlap}
        if listed != counts or len(listed) != len(self.overlap):
            raise ValueError("overlap does not match the intersection of topics and sections")
        return self
