"""Fixtures for the figure-extraction tests: a parsed+extracted project and a two-slug twin."""

from __future__ import annotations

import json
import shutil
from typing import Any

import pytest

from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json
from manuallabor.figures.pipeline import run_figures
from manuallabor.figures.types import FigureExtraction, FigureIndex, FigureReport
from manuallabor.ingest import ingest_files
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths
from tests.conftest import FIXTURES, Parsed

GT_STEMS = ("figures", "twocol", "clean", "scanned", "manual")


def load_gt(stem: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "ground_truth" / f"{stem}.json").read_text())
    return data


def sidecar(paths: ProjectPaths, slug: str, fid: str) -> FigureRecord:
    return read_json(paths.figure_file(slug, fid, "json"), FigureRecord)


def report(paths: ProjectPaths, slug: str) -> FigureReport:
    return read_json(paths.doc(slug).figure_report, FigureReport)


def entry(paths: ProjectPaths, slug: str, fid: str) -> FigureExtraction:
    return next(f for f in report(paths, slug).figures if f.figure_id == fid)


def index(paths: ProjectPaths) -> FigureIndex:
    return read_json(paths.figures_index, FigureIndex)


@pytest.fixture(scope="session")
def figproj(parsed: Parsed, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    root = tmp_path_factory.mktemp("figproj") / "proj"
    shutil.copytree(parsed.paths.root, root)
    paths = ProjectPaths(root)
    assert run_figures(paths, emit=lambda _o: None) == []
    return paths


@pytest.fixture(scope="session")
def twin(parsed: Parsed, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    """figures.pdf ingested twice: as `figures` and as `figures-copy`."""
    base = tmp_path_factory.mktemp("twin")
    root = base / "proj"
    shutil.copytree(parsed.paths.root, root)
    paths = ProjectPaths(root)
    copy = base / "figures-copy.pdf"
    shutil.copyfile(FIXTURES / "figures.pdf", copy)
    ingest_files(paths, [copy], emit=lambda _o: None)
    assert parse_project(paths, only="figures-copy", emit=lambda _o: None) == 0
    assert run_figures(paths, emit=lambda _o: None) == []
    return paths
