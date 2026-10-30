from __future__ import annotations

import contextlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts import ModelRef, ProjectConfig, Task
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import TaskModels
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.figures.pipeline import run_figures
from manuallabor.ingest import ingest_files
from manuallabor.parse.pdf_docling import models_cached
from manuallabor.parse.pipeline import parse_project
from manuallabor.parse.types import PageLayout
from manuallabor.project import ProjectPaths
from manuallabor.providers import CorruptingMockProvider, ListSink, MockProvider, ProviderSet
from manuallabor.providers.cache import LLMCache
from manuallabor.scoring.pipeline import block_contexts, run_score
from manuallabor.scoring.types import BlockContext

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


def copy_project(src: Path, dst: Path) -> Path:
    """Copy a project minus the parse-only page renders (downstream stages never read them)."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("pages"))
    return dst


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
        models=TaskModels(
            cleanup=ref,
            grouping=ref,
            vision=ref,
            embeddings=ref,
            verifier=ModelRef(provider="mock", model="mock-verifier"),
        ),
    )


# --- shared scoring helpers and fixtures (moved from tests/scoring/conftest.py) ---

SLUG = "doc"


def make_block(
    raw: str = "Check the drive belt.",
    *,
    n: int = 1,
    page: int = 1,
    type: BlockType = BlockType.paragraph,
    source: str = "pymupdf",
    texts: dict[str, str] | None = None,
    order: dict[str, int] | None = None,
    reading_order: int | None = None,
    **kw: Any,
) -> Block:
    if texts is None:
        texts = {"pymupdf": raw, "docling": raw} if source in ("pymupdf", "docling") else {}
    return Block(
        id=f"b-{SLUG}-p{page:03d}-{n:02d}",
        doc_id=SLUG,
        page=page,
        bbox=[0, 0, 10, 10],
        type=type,
        reading_order=n if reading_order is None else reading_order,
        raw_text=raw,
        raw_source=source,
        raw_text_by_parser=texts,
        order_by_parser=order or {},
        **kw,
    )


def ctx(**kw: Any) -> BlockContext:
    base: dict[str, Any] = {
        "parser_versions": {"pymupdf": "x", "docling": "y", "ocr": "t", "ocr_alt": "r"},
        "product_model": "Acme X200",
        "hf_strings": ["Acme X200 Service Manual", "Page 3"],
    }
    base.update(kw)
    return BlockContext(**base)


@dataclass
class Scored:
    paths: ProjectPaths

    def doc(self, slug: str) -> Document:
        return read_json(self.paths.doc(slug).document, Document)

    def blocks(self, slug: str) -> list[Block]:
        return read_json_list(self.paths.doc(slug).blocks, Block)

    def layouts(self, slug: str) -> list[PageLayout]:
        return read_json_list(self.paths.doc(slug).layout, PageLayout)

    def contexts(self, slug: str, blocks: list[Block] | None = None) -> dict[str, BlockContext]:
        return block_contexts(self.doc(slug), blocks or self.blocks(slug), self.layouts(slug))


@pytest.fixture(scope="session")
def figproj_scoring(parsed: Parsed, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    root = tmp_path_factory.mktemp("figproj-scoring") / "proj"
    copy_project(parsed.paths.root, root)
    paths = ProjectPaths(root)
    assert run_figures(paths, emit=lambda _o: None) == []
    return paths


@pytest.fixture(scope="session")
def scoredproj(figproj_scoring: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> Scored:
    root = tmp_path_factory.mktemp("scoredproj") / "proj"
    copy_project(figproj_scoring.root, root)
    paths = ProjectPaths(root)
    assert run_score(paths, emit=lambda _o: None) == []
    return Scored(paths)


@pytest.fixture
def scored_copy(scoredproj: Scored, tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "scored"
    copy_project(scoredproj.paths.root, root)
    return ProjectPaths(root)


# --- disk guard: the shared basetemp must stay small ---

# Raised from 2 GiB on 2026-10-30: the full suite leaves ~2.1 GiB (647 dirs, ~3.7 MiB avg).
MAX_TMP_BYTES = 3 * 1024**3


def _tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, f)).st_size
    return total


@pytest.fixture(scope="session", autouse=True)
def _tmp_footprint_guard(tmp_path_factory: pytest.TempPathFactory) -> Any:
    yield
    base = tmp_path_factory.getbasetemp()
    size = _tree_bytes(base)
    print(f"\n[tmp footprint] {base}: {size / 1024**2:.0f} MiB")
    if size > MAX_TMP_BYTES:
        pytest.fail(f"pytest basetemp {base} is {size / 1024**3:.2f} GiB (> 3 GiB cap)")


# --- module 7 fixtures: a two-document project (clean.pdf + scanned.pdf), mock models ---------


def labor_copy(src: Path, dst: Path, *, db: bool = False) -> Path:
    """Copy a project minus page renders, logs, locks and (unless `db`) the state database."""
    patterns = ["pages", "pages_view", "logs", ".labor*.lock", ".uploads", "sources"]
    if not db:
        patterns += ["project.db", "project.db-*"]
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*patterns))
    if (src / "sources").is_dir():  # the PDFs are read-only inputs: share them (disk guard)
        (dst / "sources").symlink_to((src / "sources").resolve(), target_is_directory=True)
    return dst


@pytest.fixture(scope="session")
def labor_template(requires_docling: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ingested, parsed and figure-extracted clean.pdf + scanned.pdf (no scoring yet).
    MANUALLABOR_TEST_TEMPLATE=<dir> reuses a prebuilt one (a development shortcut)."""
    prebuilt = os.environ.get("MANUALLABOR_TEST_TEMPLATE")
    if prebuilt:
        return Path(prebuilt)
    root = tmp_path_factory.mktemp("labor-template") / "proj"
    root.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    ingest_files(paths, [FIXTURES / "clean.pdf", FIXTURES / "scanned.pdf"], emit=lambda _o: None)
    assert parse_project(paths, emit=lambda _o: None) == 0
    assert run_figures(paths, emit=lambda _o: None) == []
    return root


@pytest.fixture(scope="session")
def labor_scored(labor_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """labor_template run through score2 by the executor (mock models), with its project.db."""
    from manuallabor.jobs.inline import run_inline
    from manuallabor.state.models import RunPlanIn
    from manuallabor.state.store import Store

    root = tmp_path_factory.mktemp("labor-scored") / "proj"
    labor_copy(labor_template, root)
    paths = ProjectPaths(root)
    store = Store.open(paths)
    res = run_inline(paths, RunPlanIn(to="score2"), mode="mock", emit=lambda _o: None, store=store)
    store.close()
    assert res.ok
    return root


@pytest.fixture
def lp(labor_scored: Path, tmp_path: Path) -> ProjectPaths:
    """A fresh copy of the scored project (no project.db)."""
    return ProjectPaths(labor_copy(labor_scored, tmp_path / "proj"))
