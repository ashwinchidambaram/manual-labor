"""Tests 26 and 27 (slow): the 200-page stress parse and the scanned wall-time budget."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pymupdf
import pytest

from manuallabor.ingest import ingest_files
from manuallabor.parse.pipeline import parse_project
from manuallabor.project import ProjectPaths
from tests.parse.conftest import FIXTURES
from tests.subproc import run_bounded

pytestmark = pytest.mark.slow


def _project(tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    return ProjectPaths(root)


def test_26_two_hundred_pages(requires_docling: None, tmp_path: Path) -> None:
    src = tmp_path / "stress.pdf"
    out = pymupdf.open()
    with pymupdf.open(FIXTURES / "clean.pdf") as clean:
        for _ in range(18):
            out.insert_pdf(clean, from_page=1, to_page=11)
        out.insert_pdf(clean, from_page=1, to_page=2)
    assert out.page_count == 200
    out.save(src)
    out.close()
    paths = _project(tmp_path)
    t0 = time.perf_counter()
    ingest_files(paths, [src], emit=lambda _o: None)
    failed = parse_project(paths, emit=lambda _o: None)
    wall = time.perf_counter() - t0
    print(f"200-page wall time: {wall:.1f} s")
    assert failed == 0
    assert wall < 300
    assert len(paths.load_document("stress").block_ids) > 1000


def test_27_scanned_wall_time(requires_docling: None, tmp_path: Path) -> None:
    paths = _project(tmp_path)
    ingest_files(paths, [FIXTURES / "scanned.pdf"], emit=lambda _o: None)
    t0 = time.perf_counter()
    proc = run_bounded(
        [sys.executable, "-c", "from manuallabor.cli import app; app()", "parse", str(paths.root)],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )
    wall = time.perf_counter() - t0
    print(f"scanned.pdf wall time: {wall:.1f} s")
    assert proc.returncode == 0, proc.stdout[-1500:]
    assert wall < 90
