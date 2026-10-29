from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from manuallabor.contracts import ModelRef, ProjectConfig, Task
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import TaskModels
from manuallabor.contracts.document import Document
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.ingest import ingest_files
from manuallabor.parse.pdf_docling import models_cached
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths
from manuallabor.providers import CorruptingMockProvider, ListSink, MockProvider, ProviderSet
from manuallabor.providers.cache import LLMCache

# --- shared parse fixtures (moved from tests/parse/conftest.py) ---

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALL_FIXTURES = ("clean", "twocol", "tables", "figures", "scanned", "manual")
FILES = {
    "clean": "clean.pdf",
    "twocol": "twocol.pdf",
    "tables": "tables.pdf",
    "figures": "figures.pdf",
    "scanned": "scanned.pdf",
    "manual": "manual.docx",
}


def docling_available() -> bool:
    return models_cached()


@pytest.fixture(scope="session")
def requires_docling() -> None:
    """Skip when Docling's models are absent, unless MANUALLABOR_REQUIRE_DOCLING=1 (then fail)."""
    if docling_available():
        return
    if os.environ.get("MANUALLABOR_REQUIRE_DOCLING") == "1":
        pytest.fail("MANUALLABOR_REQUIRE_DOCLING=1 but the Docling models are not cached")
    pytest.skip("docling models not cached; run: uv run docling-tools models download")


def make_template(root: Path) -> ProjectPaths:
    """An ingested (not yet parsed) project holding the 6 fixtures with the mock project.json."""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    ingest_files(paths, [FIXTURES / FILES[k] for k in ALL_FIXTURES], emit=lambda _o: None)
    return paths


@dataclass
class Parsed:
    paths: ProjectPaths
    template: Path

    def doc(self, stem: str) -> Document:
        return read_json(self.paths.doc(stem).document, Document)

    def blocks(self, stem: str) -> list[Block]:
        return read_json_list(self.paths.doc(stem).blocks, Block)


@pytest.fixture(scope="session")
def template_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("template") / "proj"
    make_template(root)
    return root


@pytest.fixture(scope="session")
def parsed(
    requires_docling: None, template_project: Path, tmp_path_factory: pytest.TempPathFactory
) -> Parsed:
    root = tmp_path_factory.mktemp("parsed") / "proj"
    shutil.copytree(template_project, root)
    paths = ProjectPaths(root)
    failed = parse_project(paths, emit=lambda _o: None)
    assert failed == 0
    return Parsed(paths=paths, template=template_project)


@pytest.fixture
def copy_template(template_project: Path, tmp_path: Path) -> Callable[[], Path]:
    def _copy() -> Path:
        dst = tmp_path / "copy" / "proj"
        shutil.copytree(template_project, dst)
        return dst

    return _copy


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "sources").mkdir(parents=True)
    return project


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
