"""Provider modes for jobs (design 07 section 4.3): `config` (the project's configured
providers) or `mock` (every task mocked; any non-mock reference is a ProviderError, never a
network call)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from manuallabor.contracts.config import ModelRef, ProjectConfig, TaskModels
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import (
    DEFAULT_FACTORIES,
    Factory,
    LogSink,
    ProviderSet,
    _mock_factory,
    build_provider_set,
)

__all__ = [
    "MOCK_ONLY_FACTORIES",
    "ProviderMode",
    "mockify",
    "provider_set_factory",
]

ProviderMode = Literal["config", "mock"]
MOCK_ONLY_FACTORIES: dict[str, Factory] = {"mock": _mock_factory}

_TASK_FIELDS = ("cleanup", "grouping", "vision", "embeddings", "verifier", "metadata", "agent")


def mockify(cfg: ProjectConfig) -> ProjectConfig:
    """The same config with every model reference mocked. A mock reference keeps its model
    name; any other becomes `mock-<task>` (the verifier `mock-verifier`, so it never equals
    cleanup and the verifier-differs rule holds)."""
    fields: dict[str, ModelRef | None] = {}
    for task in _TASK_FIELDS:
        ref: ModelRef | None = getattr(cfg.models, task)
        if ref is None:
            fields[task] = None
        elif task == "verifier":
            fields[task] = ModelRef(
                provider="mock", model=ref.model if ref.provider == "mock" else "mock-verifier"
            )
        else:
            model = ref.model if ref.provider == "mock" else f"mock-{task}"
            fields[task] = ModelRef(provider="mock", model=model)
    models = TaskModels.model_validate(
        {k: (v.model_dump() if v is not None else None) for k, v in fields.items()}
    )
    return cfg.model_copy(update={"models": models})


def provider_set_factory(
    paths: ProjectPaths, cfg: ProjectConfig, mode: ProviderMode, sink: LogSink
) -> Callable[[], ProviderSet]:
    """A memoized factory (providers are built at first use, once)."""
    built: list[ProviderSet] = []

    def make() -> ProviderSet:
        if not built:
            if mode == "mock":
                built.append(
                    build_provider_set(
                        mockify(cfg),
                        cache_dir=paths.llm_cache,
                        sink=sink,
                        factories=MOCK_ONLY_FACTORIES,
                    )
                )
            else:
                built.append(
                    build_provider_set(
                        cfg,
                        cache_dir=paths.llm_cache,
                        sink=sink,
                        factories=DEFAULT_FACTORIES,
                    )
                )
        return built[0]

    return make
