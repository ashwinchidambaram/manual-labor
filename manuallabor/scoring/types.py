"""Internal models and every scoring constant (docs/design/03-scoring.md sections 1, 11)."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from manuallabor.contracts._base import BlockId, DocSlug, Sha256Hex, Unit, round6
from manuallabor.contracts.block import FaithfulnessResult, Signal
from manuallabor.contracts.enums import AttachRule, Extraction
from manuallabor.figures.types import DedupeEntry, FigureExtraction, FigureFailure

SCORING_ALGO_VERSION: Final = "1"

# -- comparison normalization / agreement (2.0, 2.2, 2.3) ------------------------------------
DIGIT_WEIGHT: Final = 3
NUMERIC_WINDOW: Final = 2
NUMERIC_PENALTY: Final = 0.5
AGREEMENT_CRITICAL_BELOW: Final = 0.8
SINGLE_SOURCE_VALUE: Final = 0.6
OCR_EMPTY_VALUE: Final = 0.5
MAX_NOTES: Final = 3
DETAIL_MAX: Final = 200

# -- reading order (2.5) ---------------------------------------------------------------------
RO_DISPLACED: Final = 0.4
RO_OVERLAP: Final = 0.3
RO_MULTICOL: Final = 0.1

# -- tables (2.6) ----------------------------------------------------------------------------
TABLE_SINGLE_PARSER: Final = 0.7
TABLE_NO_STRUCTURE: Final = 0.5
TABLE_NO_HEADER: Final = 0.8
TABLE_RAGGED_WEIGHT: Final = 0.5

# -- garbage (2.7) ---------------------------------------------------------------------------
GARBAGE_FRAG_FREE: Final = 0.2
GARBAGE_FRAG_SLOPE: Final = 2.0

# -- figures (2.9) ---------------------------------------------------------------------------
FIG_BASE: Final = {Extraction.native: 1.0, Extraction.vector: 0.95, Extraction.crop: 0.70}
FIG_CAP: Final = 0.5
FIG_SMALL_PT: Final = 36.0
FIG_SMALL_FRAC: Final = 0.002
FIG_DPI_FULL: Final = 150.0
ATTACH: Final = {
    AttachRule.caption_ref: 1.0,
    AttachRule.caption_match: 0.9,
    AttachRule.proximity: 0.6,
    AttachRule.none: 0.4,
}

# -- verifier (2.10) -------------------------------------------------------------------------
VERIFIER_FLAG_VALUE: Final = 0.2
VERIFIER_MAX_SPAN: Final = 300

# -- faithfulness (4) ------------------------------------------------------------------------
FAITH_REORDER_VALUE: Final = 0.9
REORDER_MAX_UNITS: Final = 200
REORDER_MAX_STEPS: Final = 10_000
FAITH_MAX_CHARS: Final = 50_000
FAITH_REWRITE_QUICK_RATIO: Final = 0.5


class ScoringError(Exception):
    """A document cannot be scored (missing input, canonicalizer self-test failure)."""


def clamp01(x: float) -> float:
    return round6(min(1.0, max(0.0, x)))


def truncate(detail: str, limit: int = DETAIL_MAX) -> str:
    return detail if len(detail) <= limit else detail[: limit - 1] + "…"


class ScoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=False)


class ReorderEvidence(ScoreModel):
    """Evidence that a reading-order fix is legitimate (4.5)."""

    layout_risk: bool = False
    alt_texts: tuple[str, ...] = ()


class FigureInputs(ScoreModel):
    extraction: FigureExtraction | None = None
    failure: FigureFailure | None = None
    dedupe: DedupeEntry | None = None
    attach_rule: AttachRule = AttachRule.none
    articles: list[str] = Field(default_factory=list)


class BlockContext(ScoreModel):
    """Everything about a block's surroundings that its signals need (pure inputs)."""

    displaced_in: list[str] = Field(default_factory=list)
    in_overlap: bool = False
    n_columns: int | None = None
    parser_versions: dict[str, str] = Field(default_factory=dict)
    product_model: str | None = None
    hf_strings: list[str] = Field(default_factory=list)

    @property
    def layout_risk(self) -> bool:
        return bool(self.displaced_in) or self.in_overlap or (self.n_columns or 0) >= 2


class BlockScore(ScoreModel):
    block_id: BlockId
    signals: list[Signal]
    confidence: Unit | None
    status: Literal["auto_approved", "queued"]
    has_numeric_spec: bool
    numeric_specs: list[str] = Field(default_factory=list)
    faithfulness: FaithfulnessResult | None = None


class ScoreFile(ScoreModel):
    doc_id: DocSlug
    algo_version: str
    fingerprint: Sha256Hex
    threshold: Unit
    blocks: list[BlockScore]


class HistoryEntry(ScoreModel):
    seq: int = Field(ge=1)
    block_id: BlockId
    fingerprint: str
    confidence: Unit | None
    status: Literal["auto_approved", "queued"]
    signals: list[Signal]
