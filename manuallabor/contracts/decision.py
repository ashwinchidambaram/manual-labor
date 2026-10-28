"""Calibration decision record (SPEC 5.4)."""

from __future__ import annotations

from pydantic import Field, model_validator

from manuallabor.contracts._base import BlockId, ContractModel, FlagId, Unit, UTCDateTime
from manuallabor.contracts.block import Signal
from manuallabor.contracts.enums import DecisionAction


class Decision(ContractModel):
    seq: int = Field(ge=1)
    block_id: BlockId
    action: DecisionAction
    score: Unit | None
    threshold: Unit
    signals: list[Signal]
    edited_text: str | None = None
    flag_id: FlagId | None = None
    timestamp: UTCDateTime

    @model_validator(mode="after")
    def _check(self) -> Decision:
        if (self.edited_text is not None) != (self.action == DecisionAction.edit):
            raise ValueError("edited_text must be set if and only if action == edit")
        if (self.flag_id is not None) != (self.action == DecisionAction.flag):
            raise ValueError("flag_id must be set if and only if action == flag")
        return self
