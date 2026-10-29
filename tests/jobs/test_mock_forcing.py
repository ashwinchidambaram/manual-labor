"""G9: mock mode forces every provider to the mock, and nothing touches the network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from manuallabor.contracts.config import ModelRef, ProjectConfig, TaskModels
from manuallabor.contracts.io import write_json
from manuallabor.jobs.providers import mockify


def ollama_config() -> ProjectConfig:
    o = ModelRef(provider="ollama", model="llama3.2:1b")
    return ProjectConfig(
        name="live-ish",
        models=TaskModels(
            cleanup=o,
            grouping=o,
            vision=ModelRef(provider="ollama", model="moondream"),
            embeddings=ModelRef(provider="ollama", model="nomic-embed-text"),
            verifier=ModelRef(provider="ollama", model="qwen2.5:1.5b"),
            metadata=ModelRef(provider="anthropic", model="claude-x"),
            agent=ModelRef(provider="openai", model="gpt-x"),
        ),
    )


def test_mockify_maps_every_reference_and_keeps_the_config_valid() -> None:
    m = mockify(ollama_config())
    refs = [
        getattr(m.models, t)
        for t in ("cleanup", "grouping", "vision", "embeddings", "verifier", "metadata", "agent")
    ]
    assert all(r is not None and r.provider == "mock" for r in refs)
    assert m.models.verifier is not None and m.models.verifier.model == "mock-verifier"
    assert m.models.verifier != m.models.cleanup
    assert m.name == "live-ish" and m.threshold == ollama_config().threshold
    # a mock config maps to itself
    again = mockify(m)
    assert again.models == m.models


def test_g9_providers_are_mocks_and_the_network_is_never_touched(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    write_json(root / "project.json", ollama_config())
    r = subprocess.run(
        [sys.executable, "-m", "tests.jobs.offline_mock_child", str(root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["violations"] == [] and out["refused"] is True and out["calls"] >= 2


def test_g9_a_whole_run_in_mock_mode_on_an_ollama_project(
    labor_template: Path, tmp_path: Path
) -> None:
    """Mock mode on a project whose config points at Ollama never calls out, and every logged
    call is a mock (the project-a config is already mock; this one is rewritten)."""
    from manuallabor.jobs.inline import run_inline
    from manuallabor.project import ProjectPaths
    from manuallabor.state.models import RunPlanIn
    from manuallabor.state.store import Store
    from tests.conftest import labor_copy

    paths = ProjectPaths(labor_copy(labor_template, tmp_path / "proj"))
    write_json(paths.config, ollama_config().model_copy(update={"name": "project-a"}))
    store = Store.open(paths)
    res = run_inline(
        paths,
        RunPlanIn(to="score2", docs=["clean"]),
        mode="mock",
        emit=lambda _o: None,
        store=store,
    )
    store.close()
    assert res.ok
    rows = [json.loads(x) for x in paths.llm_log.read_text().splitlines() if x.strip()]
    assert rows and {r["provider"] for r in rows} == {"mock"}
