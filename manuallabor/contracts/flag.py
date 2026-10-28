"""Reviewer flags."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from manuallabor.contracts._base import (
    ContractModel,
    FlagId,
    TargetId,
    UTCDateTime,
    check_target_id,
)
from manuallabor.contracts.enums import FlagCategory, FlagStatus


class Flag(ContractModel):
    id: FlagId
    target_id: TargetId
    category: FlagCategory
    note: str | None = None
    status: FlagStatus = FlagStatus.open
    created_at: UTCDateTime
    resolved_at: UTCDateTime | None = None
    resolution: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Flag:
        check_target_id(self.target_id)
        if (self.status == FlagStatus.resolved) != (self.resolved_at is not None):
            raise ValueError("resolved_at must be set if and only if status == resolved")
        return self

    @property
    def target_kind(self) -> Literal["block", "figure"]:
        return "figure" if self.target_id.startswith("FIG-") else "block"
