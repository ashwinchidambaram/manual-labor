"""Project configuration and model references."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from manuallabor.contracts._base import ContractModel, Unit
from manuallabor.contracts.enums import ArticleSplit, OcrEngine, Task

KNOWN_PROVIDERS = ("mock", "ollama", "anthropic", "openai", "openai_compatible", "vllm", "llamacpp")


class ModelRef(ContractModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    model: str = Field(min_length=1)
    api_base: str | None = None
    api_key_env: str | None = None


def _default_chat() -> ModelRef:
    """Small-tier default (fits a 16 GB machine); `labor probe --apply <tier>` changes it."""
    return ModelRef(provider="ollama", model="llama3.2:1b")


def _default_vision() -> ModelRef:
    return ModelRef(provider="ollama", model="moondream")


def _default_verifier() -> ModelRef:
    """A different model than the cleanup default: a verifier that is the cleanup model only
    re-reads its own output (the pipeline skips it as `skip_same_model`)."""
    return ModelRef(provider="ollama", model="qwen2.5:1.5b")


class TaskModels(ContractModel):
    cleanup: ModelRef = Field(default_factory=_default_chat)
    grouping: ModelRef = Field(default_factory=_default_chat)
    vision: ModelRef = Field(default_factory=_default_vision)
    embeddings: ModelRef = Field(
        default_factory=lambda: ModelRef(provider="ollama", model="nomic-embed-text")
    )
    verifier: ModelRef | None = Field(default_factory=_default_verifier)
    metadata: ModelRef | None = None
    agent: ModelRef | None = None

    @model_validator(mode="after")
    def _verifier_differs_from_cleanup(self) -> TaskModels:
        v, c = self.verifier, self.cleanup
        if v is not None and (v.provider, v.model, v.api_base) == (c.provider, c.model, c.api_base):
            raise ValueError(
                f"models.verifier must differ from cleanup ({c.provider}:{c.model}): "
                "a model grading its own output is not an independent check; pick another model "
                "or set models.verifier to null to disable it"
            )
        return self


class LearningConfig(ContractModel):
    """Self-improvement toggle (module 7 extends it with snapshot settings)."""

    enabled: bool = False


class CleanupConfig(ContractModel):
    """Cleanup stage settings (module 5): when the LLM pass runs, and figure descriptions."""

    llm: Literal["off", "residual", "always"] = "residual"
    describe: bool = True


class ProjectConfig(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str
    threshold: Unit = 0.85
    models: TaskModels = Field(default_factory=TaskModels)
    article_split: ArticleSplit = ArticleSplit.per_topic
    parsers: list[str] = Field(default_factory=lambda: ["pymupdf", "docling"])
    ocr_engine: OcrEngine = OcrEngine.auto
    ocr_dpi: int = Field(default=300, ge=300)
    background_ocr_born_digital: bool = True
    target_edit_rate: Unit = 0.02
    learning: LearningConfig = Field(default_factory=LearningConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)

    @field_validator("parsers")
    @classmethod
    def _check_parsers(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("parsers: at least 2 parsers are required")
        if len(set(v)) != len(v):
            raise ValueError("parsers: entries must be unique")
        return v

    def model_for(self, task: Task) -> ModelRef | None:
        m = self.models
        if task == Task.metadata:
            return m.metadata or m.grouping
        if task == Task.agent:
            return m.agent or m.cleanup
        return getattr(m, task.value)  # type: ignore[no-any-return]
