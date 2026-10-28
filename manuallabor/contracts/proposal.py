"""Agent-pass proposals (SPEC 5.5)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, computed_field, field_validator, model_validator

from manuallabor.contracts._base import (
    BBox,
    ContractModel,
    FlagId,
    ProposalId,
    Sha256Hex,
    TargetId,
    UTCDateTime,
)
from manuallabor.contracts.enums import ProposalStatus


class RecheckResult(ContractModel):
    check: str
    passed: bool
    detail: str | None = None


class PriorAttempt(ContractModel):
    proposal_id: str
    proposal_text: str
    rationale: str
    status: ProposalStatus
    decided_at: UTCDateTime


class Proposal(ContractModel):
    id: ProposalId
    flag_id: FlagId
    target_id: TargetId
    round: int = Field(default=1, ge=1)
    proposal_text: str | None = None
    proposed_bbox: BBox | None = None
    evidence: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=300)
    rechecks: list[RecheckResult] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.pending
    final_text: str | None = None
    history: list[PriorAttempt] = Field(default_factory=list)
    model: str
    input_hash: Sha256Hex
    created_at: UTCDateTime

    @model_validator(mode="before")
    @classmethod
    def _drop_computed(cls, data: Any) -> Any:
        if isinstance(data, dict) and "all_checks_passed" in data:
            data = {k: v for k, v in data.items() if k != "all_checks_passed"}
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
        if (self.proposal_text is None) == (self.proposed_bbox is None):
            raise ValueError("exactly one of proposal_text / proposed_bbox must be set")
        if self.status == ProposalStatus.edited and self.final_text is None:
            raise ValueError("final_text is required when status == edited")
        if len(self.history) != self.round - 1:
            raise ValueError("history length must equal round - 1")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_checks_passed(self) -> bool:
        return all(r.passed for r in self.rechecks)
