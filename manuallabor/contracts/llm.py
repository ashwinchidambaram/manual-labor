"""LLM call records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from manuallabor.contracts._base import ContractModel, Sha256Hex, UTCDateTime, round3
from manuallabor.contracts.enums import CallKind, Task


class Message(ContractModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMCallLog(ContractModel):
    task: Task
    kind: CallKind
    provider: str
    model: str
    input_hash: Sha256Hex
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    cached: bool
    ok: bool = True
    error: str | None = None
    truncated: bool = False
    timestamp: UTCDateTime

    @field_validator("latency_ms")
    @classmethod
    def _round(cls, v: float) -> float:
        return round3(v)


class ChatResult(ContractModel):
    text: str
    parsed: Any | None = None
    log: LLMCallLog
