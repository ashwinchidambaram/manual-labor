"""C1-C5: `labor check`."""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from manuallabor.check import CheckCtx, run_check
from manuallabor.contracts.config import ModelRef, ProjectConfig, TaskModels
from manuallabor.contracts.io import write_json
from tests.conftest import FIXTURES, labor_copy

LABOR = [sys.executable, "-m", "manuallabor"]
PROJECT_A = FIXTURES / "project-a"


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(root)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def temp_dirs() -> set[str]:
    return set(glob.glob(str(Path(tempfile.gettempdir()) / "labor-check-*")))


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_c1_gate_labor_check_project_a(requires_docling: None) -> None:
    before_tree, before_tmp = tree_hash(PROJECT_A), temp_dirs()
    r = subprocess.run(
        [*LABOR, "check", str(PROJECT_A)], capture_output=True, text=True, timeout=600
    )
    assert r.returncode == 0, r.stdout + r.stderr[-2000:]
    for k in ("K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9"):
        line = next(x for x in r.stdout.splitlines() if x.startswith(k))
        assert " PASS " in line, line
    assert "pipeline run" in r.stdout and "PASS" in r.stdout
    assert "FAIL" not in r.stdout
    assert tree_hash(PROJECT_A) == before_tree  # the source tree is untouched
    assert temp_dirs() == before_tmp  # the temp copy was removed
    assert not (PROJECT_A / "project.db").exists()


def test_c2_a_failing_check_exits_1_and_keeps_the_copy(
    labor_template: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = labor_copy(labor_template, tmp_path / "proj")

    def failing(ctx: CheckCtx) -> str | None:
        raise AssertionError("deliberate")

    before = temp_dirs()
    code = run_check(proj, extra_checks=[("Kx failing", failing)])
    out = capsys.readouterr().out
    assert code == 1
    assert "Kx failing" in out and "FAIL" in out and "deliberate" in out
    new = temp_dirs() - before
    assert len(new) == 1 and str(next(iter(new))) in out  # kept, and its path is printed
    shutil.rmtree(next(iter(new)))


def test_c2_an_unparseable_source_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    proj = tmp_path / "bad"
    (proj / "sources").mkdir(parents=True)
    shutil.copyfile(PROJECT_A / "project.json", proj / "project.json")
    (proj / "sources" / "broken.pdf").write_text("this is not a pdf")
    before = temp_dirs()
    code = run_check(proj)
    out = capsys.readouterr().out
    assert code == 1 and "pipeline run" in out and "FAIL" in out
    for d in temp_dirs() - before:
        shutil.rmtree(d)


def test_c3_live_skips_cleanly_when_ollama_is_unreachable() -> None:
    env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{closed_port()}"}
    env.pop("MANUALLABOR_LIVE_REQUIRED", None)
    before = temp_dirs()
    r = subprocess.run(
        [*LABOR, "check", "--live", str(PROJECT_A)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "SKIP live:" in r.stdout and "pipeline run" not in r.stdout  # no stage ran
    assert temp_dirs() == before
    r = subprocess.run(
        [*LABOR, "check", "--live", str(PROJECT_A)],
        capture_output=True,
        text=True,
        env={**env, "MANUALLABOR_LIVE_REQUIRED": "1"},
        timeout=120,
    )
    assert r.returncode == 4 and "SKIP live:" in r.stdout


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MANUALLABOR_LIVE") != "1", reason="needs MANUALLABOR_LIVE=1")
def test_c4_live_check_passes_with_the_small_tier(requires_docling: None) -> None:
    r = subprocess.run(
        [*LABOR, "check", "--live", str(PROJECT_A)], capture_output=True, text=True, timeout=3000
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "SKIP live" not in r.stdout and "all checks passed" in r.stdout


def test_c5_ollama_config_is_forced_to_mocks(
    labor_template: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = labor_copy(labor_template, tmp_path / "proj")
    o = ModelRef(provider="ollama", model="llama3.2:1b")
    cfg = ProjectConfig(
        name="project-a",
        models=TaskModels(
            cleanup=o,
            grouping=o,
            vision=ModelRef(provider="ollama", model="moondream"),
            embeddings=ModelRef(provider="ollama", model="nomic-embed-text"),
            verifier=ModelRef(provider="ollama", model="qwen2.5:1.5b"),
        ),
    )
    write_json(proj / "project.json", cfg)
    before = temp_dirs()
    code = run_check(proj)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "K7 mock only" in out and "all mock" in out
    assert temp_dirs() == before
    # the project's own config is untouched
    assert (
        ProjectConfig.model_validate_json((proj / "project.json").read_text()).models.cleanup == o
    )
