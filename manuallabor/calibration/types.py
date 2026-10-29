"""Calibration constants and models (design 10 sections 4, 5, 9). Pure data: no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import Field

from manuallabor.contracts._base import ContractModel, Unit

BUCKET_WIDTH: Final = 0.05
MIN_BUCKET_N: Final = 20
MIN_SUGGEST_N: Final = 50
WILSON_Z: Final = 1.645
SUGGEST_FLOOR: Final = 0.50
SIGNAL_CUTS: Final = (0.5, 0.8, 0.9)
MIN_SIGNAL_N: Final = 40
SIGNAL_SIDE_MIN: Final = 20
SIGNAL_UNINFORMATIVE_MIN: Final = 50
RULE_MIN_SUPPORT: Final = 3
CONFUSION_MIN_SUPPORT: Final = 2
LEXICON_MIN_SUPPORT: Final = 2
LEXICON_MAX_DOC_FRAC: Final = 0.30
AB_MIN_N: Final = 30
AB_MIN_DISCORDANT: Final = 3
AGENT_EXAMPLES_K: Final = 2
AGENT_EXAMPLES_MAX: Final = 100
PROMOTE_MIN_SOFT_FRAC: Final = 0.8
PROMOTE_MIN_RATE: Final = 0.10

SuggestionReason = Literal["ok", "insufficient_data", "target_not_met"]


@dataclass(frozen=True)
class Outcome:
    """One reviewed (block, raw text) observation: what the machine scored and whether the
    human had to change the text (design 10 section 4.1)."""

    block_id: str
    raw_sha: str
    action_id: int
    score: float
    numeric: bool
    block_type: str
    doc_kind: str
    edited: bool
    source: str
    provenance: str
    signals: tuple[tuple[str, float, bool], ...]  # (name, value, critical), sorted by name
    shown_sha: str = ""
    final_sha: str | None = None
    final_text: str | None = None
    shown_text: str | None = None


class PooledRow(ContractModel):
    t: Unit
    n: int
    edited: int
    rate: Unit | None = None
    lo: Unit
    hi: Unit


class ThresholdSuggestion(ContractModel):
    suggested: Unit | None = None
    reason: SuggestionReason
    detail: str | None = None


class SignalReliability(ContractModel):
    signal: str
    cut: float
    n_below: int
    edited_below: int
    rate_below: Unit | None = None
    lo_below: Unit
    hi_below: Unit
    n_above: int
    edited_above: int
    rate_above: Unit | None = None
    lo_above: Unit
    hi_above: Unit
    klass: Literal["predictive", "uninformative", "insufficient"]
    soft_fraction_below: Unit = 0.0
    promote: bool = False


class CriticalPromotion(ContractModel):
    id: str
    signal: str
    below: float
    support: int = Field(ge=0)
    rate_below: Unit
    rate_above: Unit


class ConfusionPair(ContractModel):
    id: str
    wrong: str
    right: str
    support: int = Field(ge=1)
    examples: list[str] = Field(default_factory=list, max_length=3)


class LexiconEntry(ContractModel):
    id: str
    kind: Literal["unit", "part_keyword"]
    value: str
    support: int = Field(ge=1)


class LearnedCalibration(ContractModel):
    """learning/calibration.json. The threshold block is information only and is never
    applied; the other lists can only queue more blocks or lower confidence (scoring M3b)."""

    snapshot: str = Field(min_length=1)
    threshold: ThresholdSuggestion | None = None
    signal_reliability: list[SignalReliability] = Field(default_factory=list)
    critical_promotions: list[CriticalPromotion] = Field(default_factory=list)
    confusions: list[ConfusionPair] = Field(default_factory=list)
    lexicon: list[LexiconEntry] = Field(default_factory=list)


class AgentExample(ContractModel):
    id: str
    category: str
    block_type: str
    before: str
    after: str | None = None
    outcome: Literal["accepted", "edited", "rejected"]
    reason: str | None = None


class LearnedAgent(ContractModel):
    snapshot: str = Field(min_length=1)
    examples: list[AgentExample] = Field(default_factory=list)


class ProvenanceRate(ContractModel):
    provenance: str
    n: int
    edited: int
    edit_rate: Unit | None = None
    wilson_lo: Unit
    wilson_hi: Unit


class DiscordantPairs(ContractModel):
    b: int
    c: int


class LearnedQueue(ContractModel):
    added: int
    edited_among_added: int


class LearnPreview(ContractModel):
    confusions: list[ConfusionPair] = Field(default_factory=list)
    lexicon: list[LexiconEntry] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    promotions: list[CriticalPromotion] = Field(default_factory=list)
