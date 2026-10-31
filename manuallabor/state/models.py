"""Shared models of module 7 (design 07 section 5.2): every DTO that crosses the A/B boundary.

Contract models (Block, Flag, Decision, ...) are imported from `manuallabor.contracts`; the
models here are the API/state layer on top of them."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from manuallabor.calibration.types import (
    DiscordantPairs,
    LearnedQueue,
    LearnPreview,
    PooledRow,
    ProvenanceRate,
    SignalReliability,
)
from manuallabor.cleanup.types import AttachOverride
from manuallabor.contracts import (
    Block,
    CoverageReport,
    DiffOp,
    FaithfulnessViolation,
    FigureRecord,
    Flag,
    GroupOverride,
    ProbeResult,
    Selection,
    SuggestionTable,
)
from manuallabor.contracts._base import (
    BlockId,
    ContractModel,
    DocSlug,
    FlagId,
    TargetId,
    TopicSlug,
    Unit,
    UTCDateTime,
)
from manuallabor.contracts.config import TaskModels
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.enums import BlockStatus, BlockType, DocKind, FlagCategory
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.manifest import Override
from manuallabor.contracts.selection import ScopeSummary

__all__ = [
    "ActionKind",
    "ActionRecord",
    "BlockDetail",
    "CalibrationAB",
    "CalibrationBucket",
    "CalibrationReport",
    "Cursor",
    "DecisionRecord",
    "DocLearning",
    "DocReadiness",
    "DocStatus",
    "EditConflict",
    "ExportFlagBlocker",
    "ExportReviewSummary",
    "ExportScopeCounts",
    "ExportStatus",
    "ExportSummary",
    "FigureAttachment",
    "FigureRailItem",
    "FlagIn",
    "JobInfo",
    "LearningState",
    "LearningUse",
    "NodeState",
    "PageRef",
    "ProjectStatus",
    "QueueItem",
    "QueuePage",
    "QueueSort",
    "RegroupIn",
    "ReviewActionIn",
    "ReviewActionOut",
    "ReviewCounts",
    "RunPlanIn",
    "SelectionOp",
    "SelectionOut",
    "SnapshotInfo",
    "WhyItem",
]


class ActionKind(StrEnum):
    select = "select"
    deselect = "deselect"
    select_group = "select_group"
    deselect_group = "deselect_group"
    set_view = "set_view"
    set_split = "set_split"
    regroup_move = "regroup_move"
    regroup_rename = "regroup_rename"
    approve = "approve"
    edit = "edit"
    flag = "flag"
    skip = "skip"
    back = "back"
    resolve_flag = "resolve_flag"
    attach = "attach"
    detach = "detach"
    crop_bbox = "crop_bbox"
    cursor = "cursor"
    threshold_view = "threshold_view"
    threshold_project = "threshold_project"
    config_models = "config_models"
    learning_toggle = "learning_toggle"
    learning_snapshot = "learning_snapshot"
    learning_activate = "learning_activate"
    learning_reset = "learning_reset"
    learning_disable_item = "learning_disable_item"
    learning_publish = "learning_publish"
    proposal_accept = "proposal_accept"
    proposal_edit = "proposal_edit"
    proposal_reject = "proposal_reject"
    export_override = "export_override"
    export_run = "export_run"
    import_ = "import"
    agent_run = "agent_run"


Screen = Literal["scope", "verify", "agent", "export", "settings", "cli"]
NodeStateName = Literal["fresh", "stale", "missing", "failed"]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled", "interrupted"]


class ActionRecord(ContractModel):
    id: int = Field(ge=1)
    ts: UTCDateTime
    screen: Screen
    kind: ActionKind
    target_id: str | None = None
    doc_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    example: dict[str, Any] | None = None
    before_ref: str | None = None
    after_ref: str | None = None
    learning_provenance: str | None = None
    request_id: str | None = None


class DecisionRecord(ContractModel):
    decision: Decision
    action_id: int
    doc_id: DocSlug
    raw_sha256: str
    shown_text_sha256: str
    faith_passed: bool | None = None
    human_edit_diff: list[DiffOp] | None = None
    numbers_verified: bool = False
    learning_provenance: str = "baseline"
    source: Literal["human", "agent"] = "human"


class WhyItem(ContractModel):
    kind: Literal["signal", "rule", "stale", "learning"]
    name: str
    value: float | None = None
    critical: bool = False
    detail: str | None = None


class QueueSort(StrEnum):
    worst_first = "worst_first"
    by_page = "by_page"
    figures_only = "figures_only"


class Cursor(ContractModel):
    sort: QueueSort = QueueSort.worst_first
    view_threshold: Unit | None = None
    doc_filter: DocSlug | None = None
    current_block_id: BlockId | None = None
    trail: list[BlockId] = Field(default_factory=list, max_length=50)


class QueueItem(ContractModel):
    block_id: BlockId
    doc_id: DocSlug
    page: int
    type: BlockType
    confidence: float | None = None
    status: BlockStatus
    has_numeric_spec: bool = False
    reasons: list[str] = Field(default_factory=list, max_length=3)
    stale_doc: bool = False
    # card fields (design 13 section 2.8.3), deterministic rules in manuallabor.state.card;
    # defaults keep recorded action outcomes (which embed a QueueItem) valid
    section_title: str | None = None
    excerpt: str = ""
    weakest_word: str | None = None


class ReviewCounts(ContractModel):
    """Review counts over the in-scope, non-header/footer blocks of ready documents.

    ``queued``, ``auto_approved``, ``approved``, ``edited``, ``flagged_open`` and ``rejected``
    are each counted from the block's derived status, one bucket per status, so
    ``queued + auto_approved + approved + edited + flagged_open + rejected == in_scope`` is a
    check over independently derived fields, not arithmetic. ``pending`` (the queue as shown,
    which depends on the view threshold) and ``skipped`` are views, not buckets."""

    pending: int = 0
    auto_approved: int = 0
    approved: int = 0
    edited: int = 0
    flagged_open: int = 0
    skipped: int = 0
    in_scope: int = 0
    queued: int = 0
    rejected: int = 0


class DocReadiness(ContractModel):
    doc_id: DocSlug
    state: Literal["ready", "pending"]
    stale: bool = False
    waiting_for: str | None = None


class PageRef(ContractModel):
    doc_id: DocSlug
    page: int
    width: float
    height: float
    render_url: str | None = None
    source_url: str


class QueuePage(ContractModel):
    items: list[QueueItem]
    total: int
    counts: ReviewCounts
    docs: list[DocReadiness]
    cursor: Cursor


class LearningUse(ContractModel):
    provenance: str = "baseline"
    learned_rules: list[str] = Field(default_factory=list)
    few_shot: list[str] = Field(default_factory=list)


class FigureAttachment(ContractModel):
    article_id: str
    rule: str
    confidence: float | None = None
    anchor_block_id: BlockId | None = None


class FigureRailItem(ContractModel):
    figure_id: str
    block_id: BlockId
    record: FigureRecord
    image_url: str
    attachment: FigureAttachment | None = None
    status: BlockStatus


class BlockDetail(ContractModel):
    block: Block
    article_ids: list[str] = Field(default_factory=list)
    page: PageRef
    why: list[WhyItem] = Field(default_factory=list)
    parser_texts: dict[str, str] = Field(default_factory=dict)
    learning: LearningUse = Field(default_factory=LearningUse)
    history: list[DecisionRecord] = Field(default_factory=list)
    figures: list[FigureRailItem] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


class FlagIn(ContractModel):
    category: FlagCategory
    note: str | None = None
    target_id: TargetId | None = None


class ReviewActionIn(ContractModel):
    kind: Literal["approve", "edit", "flag", "skip", "back"]
    block_id: BlockId | None = None
    text: str | None = None
    confirm_content_change: bool = False
    flag: FlagIn | None = None
    request_id: str = Field(min_length=1)


class ReviewActionOut(ContractModel):
    action_id: int
    decision: DecisionRecord | None = None
    flag: Flag | None = None
    block_status: BlockStatus | None = None
    next: QueueItem | None = None
    cursor: Cursor
    counts: ReviewCounts


class EditConflict(ContractModel):
    violations: list[FaithfulnessViolation]
    numeric_changes: list[str]
    diff: list[DiffOp]


class SelectionOp(ContractModel):
    op: Literal["select", "deselect", "select_group", "deselect_group", "set_view", "set_split"]
    block_ids: list[BlockId] = Field(default_factory=list)
    group_id: str | None = None
    doc_id: DocSlug | None = None
    subtree: bool = False
    view: Literal["structure", "topic"] | None = None
    split: Literal["per_topic", "per_document"] | None = None
    request_id: str = Field(min_length=1)


class SelectionOut(ContractModel):
    selection: Selection
    dropped: list[BlockId] = Field(default_factory=list)
    coverage: list[CoverageReport] = Field(default_factory=list)
    summary: ScopeSummary


class RegroupIn(ContractModel):
    doc_id: DocSlug
    kind: Literal["move", "rename"]
    block_id: BlockId | None = None
    to_topic_slug: TopicSlug | None = None
    topic_slug: TopicSlug | None = None
    title: str | None = None
    request_id: str = Field(min_length=1)


class NodeState(ContractModel):
    node: str
    state: NodeStateName
    reason: str | None = None


class DocLearning(ContractModel):
    group: str = "baseline"
    clean: str = "baseline"


class RunPlanIn(ContractModel):
    to: str = "score2"
    docs: list[DocSlug] | None = None
    force: list[str] = Field(default_factory=list)
    allow_reparse: bool = False


class JobInfo(ContractModel):
    """One background job (design 07 section 4). While it runs, ``node``/``doc`` name the unit it
    is on (after the last unit: the last one finished) and ``step_done`` of ``step_total``
    ``step_unit``s is that unit's own count of pages, blocks or topics done; all three are None
    when the unit has reported no count (it has no estimate). ``progress`` is
    ``(units_done + step_done/step_total) / units_total``, monotonic. ``files`` are the file
    names an ``ingest_run`` job was given (empty for other kinds)."""

    id: str
    kind: str
    plan: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus
    progress: Unit = 0.0
    units_done: int = 0
    units_total: int = 0
    node: str | None = None
    doc: str | None = None
    step_done: int | None = Field(default=None, ge=0)
    step_total: int | None = Field(default=None, ge=1)
    step_unit: Literal["page", "block", "topic"] | None = None
    files: list[str] = Field(default_factory=list)
    message: str | None = None
    created_at: UTCDateTime
    started_at: UTCDateTime | None = None
    finished_at: UTCDateTime | None = None
    pid: int | None = None
    error: str | None = None
    resumed_from: str | None = None


class DocStatus(ContractModel):
    doc_id: DocSlug
    kind: DocKind
    pages: int
    nodes: list[NodeState]
    learning: DocLearning = Field(default_factory=DocLearning)
    orphaned_decisions: int = 0


class ProjectStatus(ContractModel):
    project: str
    docs: list[DocStatus]
    unregistered_sources: list[str] = Field(default_factory=list)
    jobs_running: list[JobInfo] = Field(default_factory=list)


class SnapshotInfo(ContractModel):
    id: str
    created_at: UTCDateTime
    parent: str | None = None
    origin: str = "project"
    source_first_action: int | None = None
    source_last_action: int | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    active: bool = False


class LearningState(ContractModel):
    enabled: bool = False
    use_global: bool = False
    contribute_global: bool = False
    active: str | None = None
    provenance: str = "baseline"
    snapshots: list[SnapshotInfo] = Field(default_factory=list)


class CalibrationBucket(ContractModel):
    lo: Unit
    hi: Unit
    n: int
    edited: int
    edit_rate: Unit | None = None
    wilson_lo: Unit = 0.0
    wilson_hi: Unit = 1.0
    sparse: bool = False


class CalibrationAB(ContractModel):
    baseline_n: int
    baseline_edit_rate: Unit | None = None
    learned_n: int
    learned_edit_rate: Unit | None = None
    verdict: Literal["learned_better", "learned_worse", "no_difference", "insufficient"]
    method: Literal["holdout", "in_sample"] = "in_sample"
    snapshot: str | None = None
    discordant: DiscordantPairs | None = None
    learned_queue: LearnedQueue | None = None
    observed: list[ProvenanceRate] = Field(default_factory=list)


class CalibrationReport(ContractModel):
    buckets: list[CalibrationBucket] = Field(default_factory=list)
    target_edit_rate: Unit
    suggested_threshold: Unit | None = None
    ab: CalibrationAB | None = None
    scope: Literal["project", "global"] = "project"
    current_threshold: Unit | None = None
    n_outcomes: int = 0
    n_numeric_excluded: int = 0
    pooled: list[PooledRow] = Field(default_factory=list)
    suggestion_reason: Literal["ok", "insufficient_data", "target_not_met"] | None = None
    suggestion_detail: str | None = None
    warnings: list[str] = Field(default_factory=list)
    signals: list[SignalReliability] = Field(default_factory=list)
    learn_preview: LearnPreview | None = None


class ExportReviewSummary(ContractModel):
    """The blocks of one export (design 11 section 14). Every exported block (assigned to an
    article in the manifest) is in exactly one bucket: ``blocks == auto_approved + approved +
    edited + overrides``; an override-covered block counts only as an override. ``left_out``
    counts the other parsed blocks by their manifest reason (``header_footer``,
    ``not_selected``, ``empty``, ``rejected``): ``total_blocks == blocks + sum(left_out)``.
    ``numbers_verified`` is the manifest's ``numbers_verified_blocks`` count, a cross-cut."""

    blocks: int = Field(ge=0)
    auto_approved: int = Field(ge=0)
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    overrides: int = Field(ge=0)
    numbers_verified: int = Field(ge=0)
    total_blocks: int = Field(ge=0)
    left_out: dict[str, int] = Field(default_factory=dict)


class ExportSummary(ContractModel):
    """What the Export screen shows after an export (SPEC 7.4)."""

    articles: int = Field(ge=0)
    figures: int = Field(ge=0)
    pages_covered: int = Field(ge=0)
    docs: int = Field(ge=0)
    review: ExportReviewSummary
    warnings: list[str] = Field(default_factory=list)
    zip_bytes: int = Field(ge=0)
    zip_sha256: str
    generated_at: UTCDateTime


class ExportScopeCounts(ContractModel):
    """Every in-scope body block of the ready documents (the Verify scope: page headers and
    footers excluded) in exactly one bucket (design 11 sections 14 and 17): ``in_scope ==
    auto_approved + approved + edited + rejected + overridden + to_review + flagged``. A block
    that is queued, flagged or carries an open flag is ``overridden`` when an active override
    covers it, else ``blocking``; a blocking block is ``flagged`` when an open flag no override
    covers holds it, else ``to_review`` (``blocking == to_review + flagged``). Every other block
    is counted by its review status. This is the one partition every screen reads: "to review"
    is ``to_review``, never a block an override covers."""

    in_scope: int = Field(ge=0)
    auto_approved: int = Field(ge=0)
    approved: int = Field(ge=0)
    edited: int = Field(ge=0)
    rejected: int = Field(ge=0)
    overridden: int = Field(ge=0)
    blocking: int = Field(ge=0)
    to_review: int = Field(ge=0)
    flagged: int = Field(ge=0)


class ExportFlagBlocker(ContractModel):
    """An open flag in scope that no override covers. A block override never covers it; only
    an override naming the flag (or a blanket one) does (design 11 P3, section 14)."""

    flag_id: FlagId
    block_id: BlockId
    category: FlagCategory
    note: str | None = None


class ExportStatus(ContractModel):
    """`unlocked` is the raw gate (no open flag, no queued in-scope block); `blockers` are the
    first blocks (reading order, at most 20) an active override does not cover: an export is
    possible iff `blockers` is empty. `flag_blockers` lists every uncovered open flag (no cap);
    `counts` partitions the scope (None from a store that is not a project store)."""

    unlocked: bool
    open_flags: int
    overrides: list[Override] = Field(default_factory=list)
    queued: int = 0
    blockers: list[BlockId] = Field(default_factory=list)
    flag_blockers: list[ExportFlagBlocker] = Field(default_factory=list)
    counts: ExportScopeCounts | None = None
    summary: ExportSummary | None = None
    zip_path: str | None = None


# Re-exported so API code has one import site for everything crossing the boundary.
__all__ += [
    "AttachOverride",
    "GroupOverride",
    "GroupsFile",
    "ProbeResult",
    "SuggestionTable",
    "TaskModels",
]
