"""Determinism, idempotence and CLI tests (design 12, tests 13, 14 and 22)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manuallabor.cli import app
from manuallabor.figures.pipeline import run_figures
from manuallabor.project import ProjectPaths
from tests.conftest import Parsed

pytestmark = pytest.mark.usefixtures("requires_docling")


def snapshot(paths: ProjectPaths) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(paths.figures_root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(paths.root))] = p.read_bytes()
    for slug in paths.list_slugs():
        rp = paths.doc(slug).figure_report
        if rp.is_file():
            out[str(rp.relative_to(paths.root))] = rp.read_bytes()
    return out


def mtimes(paths: ProjectPaths) -> dict[str, int]:
    files = [p for p in paths.figures_root.rglob("*") if p.is_file()]
    files += [paths.doc(s).figure_report for s in paths.list_slugs()]
    return {str(p): p.stat().st_mtime_ns for p in files if p.is_file()}


def test_13_deterministic_across_processes(
    parsed: Parsed, figproj: ProjectPaths, tmp_path: Path
) -> None:
    root = tmp_path / "proj"
    shutil.copytree(parsed.paths.root, root)
    env = {**os.environ, "PYTHONHASHSEED": "123"}
    res = subprocess.run(
        [sys.executable, "-c", "from manuallabor.cli import app; app()", "figures", str(root)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr[-2000:]
    a, b = snapshot(figproj), snapshot(ProjectPaths(root))
    assert a.keys() == b.keys()
    assert all(a[k] == b[k] for k in a), [k for k in a if a[k] != b[k]]
    assert any(k.endswith(".svg") for k in a)


def test_14_idempotent_and_force(figproj: ProjectPaths, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    shutil.copytree(figproj.root, root)
    paths = ProjectPaths(root)
    before_bytes, before_mtimes = snapshot(paths), mtimes(paths)
    lines: list[dict[str, object]] = []
    assert run_figures(paths, emit=lines.append) == []
    docs = [ln for ln in lines if ln["stage"] == "figures"]
    assert len(docs) == 6 and all(ln["status"] == "skip" for ln in docs)
    assert mtimes(paths) == before_mtimes
    lines.clear()
    assert run_figures(paths, force=True, emit=lines.append) == []
    assert all(ln["status"] == "done" for ln in lines if ln["stage"] == "figures")
    assert snapshot(paths) == before_bytes


def test_22_cli(parsed: Parsed, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    shutil.copytree(parsed.paths.root, root)
    runner = CliRunner()
    res = runner.invoke(app, ["figures", str(root), "--doc", "figures"])
    assert res.exit_code == 0, res.output
    lines = [json.loads(ln) for ln in res.output.splitlines() if ln.startswith("{")]
    assert [ln["stage"] for ln in lines] == ["figures", "figures_dedupe"]
    assert lines[0]["doc"] == "figures" and lines[0]["status"] == "done"
    assert lines[0]["by_method"] == {"crop": 0, "native": 8, "vector": 6}

    # an unknown slug is an error: non-zero exit
    bad = runner.invoke(app, ["figures", str(root), "--doc", "no-such-doc"])
    assert bad.exit_code != 0, bad.output

    # corrupt one document's candidate list: that doc errors, the others still run
    paths = ProjectPaths(root)
    fj = paths.doc("twocol").figures
    cands = json.loads(fj.read_text())
    fj.write_text(json.dumps(cands[1:]))
    res = runner.invoke(app, ["figures", str(root), "--force"])
    assert res.exit_code == 1
    lines = [json.loads(ln) for ln in res.output.splitlines() if ln.startswith("{")]
    status = {ln["doc"]: ln["status"] for ln in lines if ln["stage"] == "figures"}
    assert status["twocol"] == "error"
    assert all(v == "done" for k, v in status.items() if k != "twocol") and len(status) == 6
    assert not paths.doc("twocol").figure_report.exists()
