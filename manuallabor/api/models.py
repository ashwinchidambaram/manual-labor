"""Request and response models owned by the API layer (design 07 section 5.2/5.3).

Contract and state models are reused, never redefined."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts import (
    BBox,
    ContractModel,
    CoverageReport,
    GroupOverride,
    GroupsFile,
    ProbeResult,
    ProjectConfig,
    SuggestionTable,
    TaskModels,
)
from manuallabor.contracts._base import ArticleId, BlockId, DocSlug, Unit
from manuallabor.contracts.enums import BlockStatus, BlockType, DocKind
from manuallabor.state.models import (
    EditConflict,
    JobInfo,
    LearningState,
    NodeState,
    QueueSort,
)


def _rid() -> str:
    return uuid.uuid4().hex


class ApiErrorBody(ContractModel):
    detail: str
    code: str


class EditConflictBody(ApiErrorBody):
    conflict: EditConflict


class RequestIn(ContractModel):
    """Body of mutations that carry nothing but an idempotency key."""

    request_id: str = Field(default_factory=_rid, min_length=1)


class ProjectInfo(ContractModel):
    name: str
    root: str
    config: ProjectConfig
    learning: LearningState
    mock: bool
    tool_version: str


class ProbeOut(ContractModel):
    probe: ProbeResult
    suggestions: SuggestionTable


class ApplyTierIn(ContractModel):
    tier: Literal["small", "medium", "large", "api"]
    force: bool = False
    request_id: str = Field(default_factory=_rid, min_length=1)


class ApplyTierOut(ContractModel):
    models: TaskModels
    stale: list[NodeState]


class ThresholdIn(ContractModel):
    value: Unit
    reason: Literal["slider", "calibration", "cli"] = "calibration"
    request_id: str = Field(default_factory=_rid, min_length=1)


class ThresholdOut(ContractModel):
    threshold: Unit
    job: JobInfo


class SourceInfo(ContractModel):
    slug: DocSlug
    filename: str
    kind: DocKind
    pages: int
    ocr_warning: str | None = None
    nodes: list[NodeState]


class PageBlock(ContractModel):
    block_id: BlockId
    bbox: list[float]
    type: BlockType
    status: BlockStatus


class DocGroups(ContractModel):
    doc_id: DocSlug
    groups: GroupsFile
    coverage: CoverageReport


class ScopeBlockRow(ContractModel):
    id: BlockId
    type: BlockType
    status: BlockStatus
    numeric: bool


class ScopeBlocks(ContractModel):
    doc_id: DocSlug
    blocks: list[ScopeBlockRow]


class ScopeModels(ContractModel):
    models: TaskModels
    probe: ProbeResult | None = None
    suggestions: SuggestionTable | None = None


class RegroupOut(ContractModel):
    override: GroupOverride
    job: JobInfo


class ConfirmIn(ContractModel):
    request_id: str = Field(default_factory=_rid, min_length=1)


class CursorIn(ContractModel):
    sort: QueueSort = QueueSort.worst_first
    view_threshold: Unit | None = None
    doc_filter: DocSlug | None = None
    current_block_id: BlockId | None = None
    request_id: str = Field(default_factory=_rid, min_length=1)


class ResolveFlagIn(ContractModel):
    resolution: str = Field(min_length=1)
    request_id: str = Field(default_factory=_rid, min_length=1)


class AttachIn(ContractModel):
    article_id: ArticleId
    anchor_block_id: BlockId | None = None
    request_id: str = Field(default_factory=_rid, min_length=1)


class AttachOut(ContractModel):
    override: AttachOverride
    job: JobInfo


class BboxIn(ContractModel):
    bbox: BBox
    request_id: str = Field(default_factory=_rid, min_length=1)


class BboxOut(ContractModel):
    job: JobInfo


class LearningFlagsIn(ContractModel):
    enabled: bool | None = None
    use_global: bool | None = None
    contribute_global: bool | None = None
    request_id: str = Field(default_factory=_rid, min_length=1)


class AgentRunIn(ContractModel):
    docs: list[DocSlug] | None = None
    request_id: str = Field(default_factory=_rid, min_length=1)


class ProposalEditIn(ContractModel):
    text: str = Field(min_length=1)
    request_id: str = Field(default_factory=_rid, min_length=1)


class CalibrationApplyIn(ContractModel):
    threshold: Unit
    request_id: str = Field(default_factory=_rid, min_length=1)


class CalibrationApplyOut(ContractModel):
    threshold: Unit


class OverrideIn(ContractModel):
    target_id: str | None = None
    flag_id: str | None = None
    reason: str = Field(min_length=1)
    request_id: str = Field(default_factory=_rid, min_length=1)


JsonDict = dict[str, Any]
