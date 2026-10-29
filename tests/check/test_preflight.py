"""`labor check --live` preflight: Ollama up but a model missing -> SKIP with pull commands."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuallabor.check import _live_preflight
from manuallabor.contracts.io import read_json
from manuallabor.contracts.probe import (
    CpuInfo,
    OllamaModel,
    OllamaStatus,
    PlatformInfo,
    ProbeResult,
)
from manuallabor.providers import probe as pr
from tests.conftest import FIXTURES


def fake_probe(models: list[str], reachable: bool = True) -> ProbeResult:
    return ProbeResult(
        probed_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        platform=PlatformInfo(system="Darwin", machine="arm64"),
        cpu=CpuInfo(model="x", cores_physical=8, cores_logical=8),
        ram_gb=16.0,
        gpu=None,
        effective_model_memory_gb=12.0,
        disk_free_gb=100.0,
        disk_path="/",
        ollama=OllamaStatus(
            installed=True,
            version="0.1",
            host="http://127.0.0.1:11434",
            reachable=reachable,
            models=[OllamaModel(name=m, size_gb=1.0, digest="d") for m in models],
        ),
        litellm_version=None,
        notes=[],
    )


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "project.json"
    shutil.copyfile(FIXTURES / "project-a" / "project.json", p)
    return p


def test_unreachable(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr, "run_probe", lambda **_k: fake_probe([], reachable=False))
    ok, reason, pulls = _live_preflight(cfg)
    assert not ok and "not reachable" in reason and pulls == ["ollama serve"]


def test_missing_models_list_the_pull_commands(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pr, "run_probe", lambda **_k: fake_probe(["llama3.2:1b", "moondream:latest"])
    )
    ok, reason, pulls = _live_preflight(cfg)
    assert not ok and "nomic-embed-text" in reason and "qwen2.5:1.5b" in reason
    assert pulls == ["ollama pull nomic-embed-text", "ollama pull qwen2.5:1.5b"]


def test_all_present_applies_the_small_tier(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    have = ["llama3.2:1b", "moondream:latest", "nomic-embed-text:latest", "qwen2.5:1.5b"]
    monkeypatch.setattr(pr, "run_probe", lambda **_k: fake_probe(have))
    ok, reason, pulls = _live_preflight(cfg)
    assert ok, reason
    from manuallabor.contracts.config import ProjectConfig

    c = read_json(cfg, ProjectConfig)
    assert c.models.cleanup.provider == "ollama" and c.models.vision.model == "moondream"
