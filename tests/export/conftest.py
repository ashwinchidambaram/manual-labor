"""Fixtures of the export tests. The real projects are built once per session (Docling parse)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from manuallabor.project import ProjectPaths
from tests.conftest import FIXTURES
from tests.export.helpers import Exported, build_scored, export_project


@pytest.fixture(autouse=True)
def _drop_tmp_path(tmp_path: Path) -> Iterator[None]:
    yield
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture(scope="session")
def scored_a(requires_docling: None, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    """project-a (clean.pdf + figures.pdf) cleaned and scored; nothing reviewed yet."""
    root = tmp_path_factory.mktemp("export-a") / "proj"
    return build_scored(root, [FIXTURES / "clean.pdf", FIXTURES / "figures.pdf"])


@pytest.fixture(scope="session")
def exported_a(scored_a: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> Exported:
    return export_project(scored_a, tmp_path_factory.mktemp("export-a-done") / "proj")


@pytest.fixture(scope="session")
def scored_dup(requires_docling: None, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    """figures.pdf plus a byte copy under another name: every figure of the copy is a duplicate."""
    src = tmp_path_factory.mktemp("export-dup-src")
    shutil.copyfile(FIXTURES / "figures.pdf", src / "figures.pdf")
    shutil.copyfile(FIXTURES / "figures.pdf", src / "figures-copy.pdf")
    root = tmp_path_factory.mktemp("export-dup") / "proj"
    return build_scored(root, [src / "figures.pdf", src / "figures-copy.pdf"])


@pytest.fixture(scope="session")
def exported_dup(scored_dup: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> Exported:
    return export_project(scored_dup, tmp_path_factory.mktemp("export-dup-done") / "proj")


@pytest.fixture(scope="session")
def approved_a(scored_a: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    """project-a with every queued block approved by a scripted reviewer; nothing exported."""
    from manuallabor.state.store import Store
    from tests.conftest import labor_copy
    from tests.export.helpers import approve_queued

    paths = ProjectPaths(
        labor_copy(scored_a.root, tmp_path_factory.mktemp("export-a-approved") / "proj", db=True)
    )
    store = Store.open(paths)
    try:
        approve_queued(paths, store)
    finally:
        store.close()
    return paths


@pytest.fixture
def work(approved_a: ProjectPaths, tmp_path: Path) -> ProjectPaths:
    """A fresh copy of the approved project (with its database)."""
    from tests.conftest import labor_copy

    return ProjectPaths(labor_copy(approved_a.root, tmp_path / "work", db=True))


@pytest.fixture
def unreviewed(scored_a: ProjectPaths, tmp_path: Path) -> ProjectPaths:
    from tests.conftest import labor_copy

    return ProjectPaths(labor_copy(scored_a.root, tmp_path / "unreviewed", db=True))
