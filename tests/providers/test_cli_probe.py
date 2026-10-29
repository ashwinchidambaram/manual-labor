"""T8 (real detectors on this machine) and T9 (--apply)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manuallabor.cli import app
from manuallabor.contracts import ProjectConfig
from manuallabor.contracts.io import read_json
from manuallabor.contracts.probe import ProbeResult
from manuallabor.project import ProjectPaths
from manuallabor.providers import probe as pr
from tests.providers import probe_support as ps

runner = CliRunner()
TASKS = ["cleanup", "grouping", "vision", "verifier", "embeddings"]


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ProjectPaths(root).ensure_config()
    return root


def test_t8_probe_real_detectors(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    before = (root / "project.json").read_bytes()
    res = runner.invoke(app, ["probe", "--project", str(root)])
    assert res.exit_code == 0, res.output
    for t in TASKS:
        assert t in res.stdout
    assert "Commands to run yourself" in res.stdout
    pj = read_json(root / "probe.json", ProbeResult)
    assert pj.ram_gb > 0 and pj.cpu.model
    assert (root / "project.json").read_bytes() == before


def test_t8_probe_json_and_no_project() -> None:
    res = runner.invoke(app, ["probe", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.stdout)
    assert set(data) == {"probe", "suggestions"}
    ProbeResult.model_validate(data["probe"])
    assert [r["task"] for r in data["suggestions"]["rows"]] == TASKS


@pytest.fixture
def canned(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A 16 GB M3 probe with every external command recorded."""
    rr = ps.RecordingRunner()
    monkeypatch.setattr(pr, "default_runner", rr)
    original = pr.run_probe

    def fake(**kw: object) -> ProbeResult:
        return original(
            runner=rr,
            clock=lambda: ps.FIXED,
            system="Darwin",
            machine="arm64",
            env={},
            http_get=lambda u, t: ps.TAGS,
            which=lambda n: "/usr/local/bin/ollama",
            disk_free=lambda p: 50.0,
            path=kw.get("path"),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(pr, "run_probe", fake)
    return rr.calls


def test_t9_apply_small(tmp_path: Path, canned: list[list[str]]) -> None:
    root = make_project(tmp_path)
    raw = json.loads((root / "project.json").read_text())
    raw["threshold"] = 0.9
    raw["name"] = "keepme"
    (root / "project.json").write_text(json.dumps(raw))
    res = runner.invoke(app, ["probe", "--project", str(root), "--apply", "small"])
    assert res.exit_code == 0, res.output
    cfg = read_json(root / "project.json", ProjectConfig)
    assert cfg.threshold == 0.9 and cfg.name == "keepme"
    assert (cfg.models.cleanup.provider, cfg.models.cleanup.model) == ("ollama", "llama3.2:1b")
    assert cfg.models.vision.model == "moondream"
    assert cfg.models.embeddings.model == "nomic-embed-text"
    assert cfg.models.verifier is not None and cfg.models.verifier.model == "qwen2.5:1.5b"
    assert "ollama pull moondream" in res.stdout
    assert not any(c[:2] == ["ollama", "pull"] for c in canned)
    assert all(c[0] in ("sysctl", "system_profiler", "ollama") for c in canned)


def test_t9_apply_large_refused_without_force(tmp_path: Path, canned: list[list[str]]) -> None:
    root = make_project(tmp_path)
    before = (root / "project.json").read_bytes()
    res = runner.invoke(app, ["probe", "--project", str(root), "--apply", "large"])
    assert res.exit_code != 0
    assert (root / "project.json").read_bytes() == before
    forced = runner.invoke(app, ["probe", "--project", str(root), "--apply", "large", "--force"])
    assert forced.exit_code == 0, forced.output
    assert read_json(root / "project.json", ProjectConfig).models.cleanup.model == "qwen2.5:14b"
    assert not any(c[:2] == ["ollama", "pull"] for c in canned)


def test_t9_apply_api_and_usage_errors(tmp_path: Path, canned: list[list[str]]) -> None:
    root = make_project(tmp_path)
    ok = runner.invoke(app, ["probe", "--project", str(root), "--apply", "api"])
    assert ok.exit_code == 0, ok.output
    cfg = read_json(root / "project.json", ProjectConfig)
    assert cfg.models.cleanup.provider == "anthropic" and cfg.models.embeddings.provider == "openai"
    assert "sk-" not in (root / "project.json").read_text()
    assert runner.invoke(app, ["probe", "--apply", "small"]).exit_code == 2
    assert runner.invoke(app, ["probe", "--project", str(root), "--apply", "huge"]).exit_code == 2
