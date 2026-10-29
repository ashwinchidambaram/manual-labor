"""Hardware probe result and model-suggestion table (module 6)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from manuallabor.contracts._base import ContractModel, UTCDateTime

Tier = Literal["small", "medium", "large", "api"]
SpeedClass = Literal["fast", "ok", "slow", "n/a"]


def _round1(x: float) -> float:
    return round(x, 1) + 0.0


Gb = Annotated[float, Field(ge=0, allow_inf_nan=False), AfterValidator(_round1)]


class PlatformInfo(ContractModel):
    system: str
    machine: str


class CpuInfo(ContractModel):
    model: str
    cores_physical: int | None = Field(ge=1)
    cores_logical: int | None = Field(ge=1)


class GpuInfo(ContractModel):
    vendor: Literal["nvidia", "amd", "apple", "none"]
    name: str
    vram_gb: Gb | None
    unified: bool


class OllamaModel(ContractModel):
    name: str
    size_gb: Gb | None  # None when Ollama reported a negative or non-finite size
    digest: str


class OllamaStatus(ContractModel):
    installed: bool
    version: str | None
    host: str
    reachable: bool
    models: list[OllamaModel]


class ProbeResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    probed_at: UTCDateTime
    platform: PlatformInfo
    cpu: CpuInfo
    ram_gb: Gb
    gpu: GpuInfo | None
    effective_model_memory_gb: Gb
    disk_free_gb: Gb
    disk_path: str
    ollama: OllamaStatus
    litellm_version: str | None
    notes: list[str]


class TierOption(ContractModel):
    provider: str
    model: str
    approx_gb: Gb
    fits: bool
    speed_class: SpeedClass
    est_tokens_per_s: float | None = Field(ge=0, allow_inf_nan=False)
    pull_command: str | None
    present: bool
    note: str | None = None


class TaskSuggestion(ContractModel):
    task: Literal["cleanup", "grouping", "vision", "verifier", "embeddings"]
    small: TierOption
    medium: TierOption
    large: TierOption
    api: TierOption


class SuggestionTable(ContractModel):
    default_tier: Tier
    rows: list[TaskSuggestion]
    pull_commands: dict[str, list[str]] = Field(default_factory=dict)
    default_reason: str | None = None  # why default_tier is not the usual small
