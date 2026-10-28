"""Shared setup for the parse tests: one ingested template project and one parsed project."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.io import read_json, read_json_list
from manuallabor.ingest import ingest_files
from manuallabor.parse.pdf_docling import models_cached
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
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
