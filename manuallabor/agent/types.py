"""Agent-pass constants and models (design 10 sections 1, 3, 9)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import Field

from manuallabor.contracts._base import (
    ContractModel,
    DocSlug,
    FlagId,
    TargetId,
)
from manuallabor.contracts.block import VisionReading
from manuallabor.contracts.enums import FlagCategory, ProposalKind
from manuallabor.contracts.proposal import EvidenceRef, PriorAttempt, RecheckResult

AGENT_PROMPT_VERSION: Final = "agent-v1"
VREAD_PROMPT_VERSION: Final = "vread-v1"

AGENT_MAX_READER_CHARS: Final = 4000
MAX_EVIDENCE: Final = 6
RATIONALE_MAX: Final = 160
MAX_CANDIDATES: Final = 8
MAX_BBOX_CANDIDATES: Final = 6
BBOX_IOU_SAME: Final = 0.95
BBOX_TEXT_OVERLAP_MAX: Final = 0.10
BBOX_INK_MIN: Final = 0.01
BBOX_MIN_SIDE: Final = 36.0
BBOX_MIN_AREA_FRAC: Final = 0.002
BBOX_MAX_AREA_FRAC: Final = 0.9
BBOX_PAD_PT: Final = 18.0
VREAD_LONG_SIDE: Final = 1024
VREAD_DPI: Final = 300
VREAD_MARGIN_PT: Final = 4.0
VREAD_MAX_LINE: Final = 40
NOTE_MAX: Final = 500
CELLS_MAX_ROWS: Final = 200
CELLS_MAX_COLS: Final = 30
CELLS_MAX_CHARS: Final = 500
HINTS_MAX: Final = 5

# Skip outcomes decided before a job starts (design 10 section 3.1) and per-item job outcomes.
SkipOutcome = Literal["pending", "max_rounds", "unsupported", "stale_doc", "out_of_scope"]
JobOutcome = Literal["no_proposal", "error"]


class AgentError(Exception):
    """A model call or its output could not be used (the flag stays open)."""


class AgentItem(ContractModel):
    """One flag the worker will process. Everything the worker needs from the database (it has
    no DB access) travels in the job plan: the reviewer's note, the rounds so far and the text
    the reviewer saw."""

    flag_id: FlagId
    category: FlagCategory
    note: str | None = None
    target_id: TargetId
    doc_id: DocSlug
    round: int = Field(ge=1)
    priors: list[PriorAttempt] = Field(default_factory=list)
    current_text: str | None = None
    basis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentPlan(ContractModel):
    items: list[AgentItem]
    origin: str | None = None


@dataclass(frozen=True)
class Skip:
    """An item that was not processed, and why."""

    flag_id: str
    target_id: str
    outcome: SkipOutcome
    detail: str | None = None


@dataclass
class AgentInput:
    """The bundle of one item (the model sees `bundle()`); also what the rechecks read."""

    item: AgentItem
    kind: ProposalKind
    bundle: dict[str, Any]
    raw_text: str
    raw_source: str
    readers: dict[str, str]
    current: str
    candidates: list[dict[str, Any]]
    candidate_text: dict[str, str]
    vision: VisionReading | None
    max_text: int
    page_image: bytes | None = None
    page_rect: list[float] | None = None


@dataclass
class ProposalDraft:
    """The checked result of one model call, before it gets an id (the service assigns it)."""

    flag_id: str
    target_id: str
    round: int
    kind: ProposalKind
    payload: dict[str, Any]
    evidence: list[EvidenceRef]
    rationale: str
    rechecks: list[RecheckResult]
    history: list[PriorAttempt]
    vision: VisionReading | None
    basis_sha256: str
    model: str
    input_hash: str


@dataclass
class AgentOutcome:
    flag_id: str
    round: int
    outcome: str
    detail: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BboxCandidate(ContractModel):
    id: str
    bbox: list[float]
    kind: str
    area_frac: float
    overlaps_text_blocks: int
    caption: str | None = None


class AttachCandidate(ContractModel):
    id: str
    caption: str | None = None
    page: int


class TopicCandidate(ContractModel):
    slug: str
    title: str
    pages: list[int]
    similarity: float | None = None


__all__ = ["EvidenceRef"]
