from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from manuallabor.contracts import ModelRef, ProjectConfig, Task
from manuallabor.contracts.config import TaskModels
from manuallabor.providers import CorruptingMockProvider, ListSink, MockProvider, ProviderSet
from manuallabor.providers.cache import LLMCache


@pytest.fixture
def call_log() -> ListSink:
    return ListSink()


@pytest.fixture
def fixed_clock():  # type: ignore[no-untyped-def]
    return lambda: datetime(2026, 1, 1, tzinfo=UTC)


def _set(tmp_path: Path, sink: ListSink, clock, corrupt: bool) -> ProviderSet:  # type: ignore[no-untyped-def]
    cache = LLMCache(tmp_path / ".llm_cache")
    by_task = {}
    for t in Task:
        if corrupt and t == Task.cleanup:
            by_task[t] = CorruptingMockProvider(sink=sink, cache=cache, clock=clock)
        else:
            by_task[t] = MockProvider(sink=sink, cache=cache, clock=clock)
    return ProviderSet(by_task=by_task)  # type: ignore[arg-type]


@pytest.fixture
def mock_providers(tmp_path: Path, call_log: ListSink, fixed_clock) -> ProviderSet:  # type: ignore[no-untyped-def]
    return _set(tmp_path, call_log, fixed_clock, corrupt=False)


@pytest.fixture
def corrupting_providers(tmp_path: Path, call_log: ListSink, fixed_clock) -> ProviderSet:  # type: ignore[no-untyped-def]
    return _set(tmp_path, call_log, fixed_clock, corrupt=True)


@pytest.fixture
def mock_config() -> ProjectConfig:
    ref = ModelRef(provider="mock", model="mock-1")
    return ProjectConfig(
        name="project-a",
        models=TaskModels(cleanup=ref, grouping=ref, vision=ref, embeddings=ref, verifier=ref),
    )
