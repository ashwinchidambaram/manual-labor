"""Agent-pass proposals (SPEC 5.5)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, computed_field, field_validator, model_validator

from manuallabor.contracts._base import (
    ArticleId,
    BBox,
    BlockId,
    ContractModel,
    FigureId,
    FlagId,
    ProposalId,
    Sha256Hex,
    TargetId,
    TopicSlug,
    UTCDateTime,
)
from manuallabor.contracts.block import VisionReading
from manuallabor.contracts.enums import EvidenceSource, ProposalKind, ProposalStatus


class RecheckResult(ContractModel):
    check: str
    passed: bool
    detail: str | None = None


class EvidenceRef(ContractModel):
    """A span quoted from a named source. `verified`: the span occurs (whitespace collapsed) in
    that source's text; an unverified span is kept and shown struck through."""

    source: EvidenceSource
    span: str = Field(min_length=1, max_length=200)
    verified: bool = False


class ProposedAttach(ContractModel):
    figure_id: FigureId
    article_id: ArticleId
    anchor_block_id: BlockId | None = None


class ProposedRegroup(ContractModel):
    block_id: BlockId
    to_topic_slug: TopicSlug


class PriorAttempt(ContractModel):
    """An earlier round of the same flag. `reason` is the reviewer's rejection reason; the
    model's own rationale is shown to the reviewer but never fed back to the model."""

    proposal_id: str
    proposal_text: str
    rationale: str
    status: ProposalStatus
    decided_at: UTCDateTime
    kind: ProposalKind = ProposalKind.text
    reason: str | None = Field(default=None, max_length=300)
    failed_checks: list[str] = Field(default_factory=list)


class Proposal(ContractModel):
    id: ProposalId
    flag_id: FlagId
    target_id: TargetId
    round: int = Field(default=1, ge=1)
    kind: ProposalKind = ProposalKind.text
    proposal_text: str | None = None
    proposed_bbox: BBox | None = None
    proposed_cells: list[list[str]] | None = None
    proposed_attach: ProposedAttach | None = None
    proposed_regroup: ProposedRegroup | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=300)
    rechecks: list[RecheckResult] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.pending
    final_text: str | None = None
    final_bbox: BBox | None = None
    history: list[PriorAttempt] = Field(default_factory=list)
    vision: VisionReading | None = None
    basis_sha256: Sha256Hex = "0" * 64
    model: str
    input_hash: Sha256Hex
    created_at: UTCDateTime

    @model_validator(mode="before")
    @classmethod
    def _drop_computed(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "all_checks_passed" in data:
            data = {k: v for k, v in data.items() if k != "all_checks_passed"}
        ev = data.get("evidence")
        if isinstance(ev, list) and any(isinstance(e, str) for e in ev):
            known = {s.value for s in EvidenceSource}
            data = {
                **data,
                "evidence": [
                    {"source": e if e in known else "note", "span": e, "verified": False}
                    if isinstance(e, str)
                    else e
                    for e in ev
                ],
            }
        if "kind" not in data:
            kind = "text"
            for field, k in (
                ("proposed_bbox", "bbox"),
                ("proposed_attach", "attach"),
                ("proposed_regroup", "regroup"),
                ("proposed_cells", "cells"),
            ):
                if data.get(field) is not None:
                    kind = k
                    break
            data = {**data, "kind": kind}
        return data

    @field_validator("rationale")
    @classmethod
    def _one_line(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("rationale must be a single line")
        return v

    @field_validator("rechecks", mode="before")
    @classmethod
    def _sort_rechecks(cls, v: Any) -> Any:
        if isinstance(v, list):

            def key(r: Any) -> str:
                return str(r.get("check") if isinstance(r, dict) else getattr(r, "check", ""))

            return sorted(v, key=key)
        return v

    @model_validator(mode="after")
    def _check(self) -> Proposal:
        payload = {
            "proposal_text": self.proposal_text is not None,
            "proposed_cells": self.proposed_cells is not None,
            "proposed_bbox": self.proposed_bbox is not None,
            "proposed_attach": self.proposed_attach is not None,
            "proposed_regroup": self.proposed_regroup is not None,
        }
        want = {
            ProposalKind.text: {"proposal_text"},
            ProposalKind.cells: {"proposed_cells", "proposal_text"},
            ProposalKind.bbox: {"proposed_bbox"},
            ProposalKind.attach: {"proposed_attach"},
            ProposalKind.regroup: {"proposed_regroup"},
        }[self.kind]
        if {k for k, v in payload.items() if v} != want:
            raise ValueError(
                f"exactly one payload must be set for kind {self.kind.value}: {sorted(want)}"
            )
        if self.status == ProposalStatus.edited and (
            self.final_text is None and self.final_bbox is None
        ):
            raise ValueError("final_text (or final_bbox) is required when status == edited")
        if len(self.history) != self.round - 1:
            raise ValueError("history length must equal round - 1")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_checks_passed(self) -> bool:
        return all(r.passed for r in self.rechecks)
