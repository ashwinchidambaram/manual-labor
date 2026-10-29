"""Internal models and every cleanup constant (docs/design/05-cleanup.md sections 1, 4-7, 11).

Imports only contracts and scoring.types, so scoring.pipeline can read clean.json without an
import cycle."""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from manuallabor.contracts._base import (
    ArticleId,
    BlockId,
    DocSlug,
    FigureId,
    Sha256Hex,
    Unit,
)
from manuallabor.contracts.block import FaithfulnessViolation
from manuallabor.contracts.enums import ArticleSplit, AttachRule, BlockType

CLEANUP_ALGO_VERSION: Final = "1"
PROMPT_VERSION: Final = "clean-v1"
DESCRIBE_PROMPT_VERSION: Final = "desc-v1"
BASELINE: Final = "baseline"

# -- deterministic passes (2) ----------------------------------------------------------------
AMBIGUOUS_PREFIXES: Final = frozenset(
    {
        "self", "non", "pre", "post", "re", "co", "anti", "multi", "semi", "sub", "cross",
        "well", "half", "low", "high", "over", "under",
    }
)  # fmt: skip
ENUM_RE: Final = re.compile(r"^(?:\(?\d{1,2}[.)]|[a-z][.)])\s")
UNAMBIGUOUS_BULLETS: Final = "•◦▪‣●"

# -- attachment (5) --------------------------------------------------------------------------
T_MATCH: Final = 0.6
MATCH_MIN_TOKENS: Final = 2
RANGE_MAX: Final = 20
_STOPWORDS_TEXT: Final = """
    the and for are but not you all any can had her was one our out has him his how its may
    new now see two who did get let put say she too use with that this from they will been
    have into more than then them were what when which while there their these those each
    must only also such both other some your over under
    figure fig view diagram overview layout detail typical shown showing
"""
STOPWORDS: Final = frozenset(_STOPWORDS_TEXT.split())

# -- learning (7) ----------------------------------------------------------------------------
FEW_SHOT_K: Final = 2
FEW_SHOT_MAX_CHARS: Final = 600

# -- storage limits (4, 6) -------------------------------------------------------------------
REJECTED_TEXT_MAX: Final = 2000
MAX_STORED_VIOLATIONS: Final = 5
EVIDENCE_TEXT_MAX: Final = 120
DESC_MAX: Final = 300
TAGS_MAX: Final = 8

ResidualReason = Literal["ambiguous_hyphen", "mid_sentence_break", "reading_order"]
Stage = Literal["raw", "deterministic", "llm"]
LlmMode = Literal["off", "residual", "always"]
LlmOutcomeKind = Literal["accepted", "rejected", "error"]
# "detached": a selected figure whose every attachment a human override removed
UnattachedReason = Literal["not_selected", "extraction_failed", "detached"]
UnresolvedReason = Literal["no_such_figure", "ambiguous_number"]
DescribeOutcome = Literal[
    "ok", "invalid", "error", "skipped_not_in_scope", "skipped_failed", "skipped_disabled"
]
LearnedKind = Literal["hyphen_keep", "hyphen_drop", "bullet_glyph"]

CLEANABLE: Final = frozenset(
    {
        BlockType.paragraph,
        BlockType.list,
        BlockType.heading,
        BlockType.caption,
        BlockType.other,
        BlockType.table,
    }
)
LLM_TYPES: Final = frozenset({BlockType.paragraph, BlockType.list, BlockType.other})


class CleanupError(Exception):
    """A document cannot be cleaned (missing input, stale prerequisite)."""


class CModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# -- clean.json ------------------------------------------------------------------------------


class LlmOutcome(CModel):
    outcome: LlmOutcomeKind
    reason: str | None = None


class RejectedCandidate(CModel):
    stage: Literal["deterministic", "llm"]
    reason: str
    detail: str | None = None  # e.g. the offending chars of a ``chars`` rejection
    text: str = Field(max_length=REJECTED_TEXT_MAX)
    violations: list[FaithfulnessViolation] = Field(
        default_factory=list, max_length=MAX_STORED_VIOLATIONS
    )


class CleanEntry(CModel):
    block_id: BlockId
    input_hash: Sha256Hex
    clean_text: str
    stage: Stage
    passes: list[str] = Field(default_factory=list)
    dh: list[str] = Field(default_factory=list)
    passes_rejected: list[str] = Field(default_factory=list)
    residual: list[ResidualReason] = Field(default_factory=list)
    llm: LlmOutcome | None = None
    rejected: list[RejectedCandidate] = Field(default_factory=list)
    fallback: bool = False
    faith_passed: bool
    alignment_ratio: Unit
    learned_rules: list[str] = Field(default_factory=list)
    few_shot: list[str] = Field(default_factory=list)


class CleanFile(CModel):
    doc_id: DocSlug
    algo_version: str
    fingerprint: Sha256Hex
    scoring_algo: str
    cleanup_model: str | None
    llm_mode: LlmMode
    prompt_version: str
    learning_snapshot: str
    blocks: list[CleanEntry]


# -- attach.json -----------------------------------------------------------------------------


class AttachEvidence(CModel):
    block_id: BlockId | None = None
    text: str | None = Field(default=None, max_length=EVIDENCE_TEXT_MAX)
    tokens: list[str] = Field(default_factory=list)


class Attachment(CModel):
    figure_id: FigureId
    rule: AttachRule
    confidence: Unit
    anchor_block_id: BlockId | None
    evidence: AttachEvidence = Field(default_factory=AttachEvidence)


class ArticleAttachments(CModel):
    article_id: ArticleId
    figures: list[Attachment]


class Unattached(CModel):
    figure_id: FigureId
    reason: UnattachedReason


class UnresolvedRef(CModel):
    block_id: BlockId
    ref: str
    reason: UnresolvedReason


class AttachFile(CModel):
    doc_id: DocSlug
    algo_version: str
    fingerprint: Sha256Hex
    article_split: ArticleSplit
    articles: list[ArticleAttachments]
    unattached: list[Unattached]
    unresolved_refs: list[UnresolvedRef]
    overrides_applied: int = Field(ge=0)
    overrides_stale: list[int]


class AttachOverride(CModel):
    seq: int = Field(ge=1)
    op: Literal["attach", "detach"]
    figure_id: FigureId
    article_id: ArticleId
    anchor_block_id: BlockId | None = None


# -- describe.json ---------------------------------------------------------------------------


class DescribeEntry(CModel):
    figure_id: FigureId
    image_sha256: Sha256Hex | None
    outcome: DescribeOutcome
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class DescribeFile(CModel):
    doc_id: DocSlug
    algo_version: str
    fingerprint: Sha256Hex
    vision_model: str | None
    prompt_version: str
    figures: list[DescribeEntry]


# -- learning (7) ----------------------------------------------------------------------------


class LearnedRule(CModel):
    id: str = Field(min_length=1)
    kind: LearnedKind
    value: str = Field(min_length=1)
    block_types: list[BlockType] = Field(default_factory=list)
    support: int = Field(ge=3)
    enabled: bool = True


class FewShotExample(CModel):
    id: str = Field(min_length=1)
    block_type: BlockType
    ocr: bool = False
    residual: list[str] = Field(default_factory=list)
    raw: str
    clean: str


class LearnedCleanup(CModel):
    snapshot: str = Field(min_length=1)
    rules: list[LearnedRule] = Field(default_factory=list)
    examples: list[FewShotExample] = Field(default_factory=list)


def fallback_detail(entry: CleanEntry) -> str | None:
    """Why a cleanup candidate was rejected, for scoring's faithfulness detail (S2); None when
    the entry is not a fallback."""
    if not entry.fallback:
        return None
    parts = [f"{r.stage}: {r.reason}" for r in entry.rejected]
    if entry.passes_rejected:
        parts.append("pass: " + ", ".join(entry.passes_rejected))
    return "; ".join(parts) if parts else "rejected"
