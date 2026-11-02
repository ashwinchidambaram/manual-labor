"""Fail fast when a model service is unreachable (design 07 section 20).

With Ollama stopped, a job read, extracted and scored for 30 s, then failed with "group
pump-service-tables: stage failed"; nothing said the service was down or what to do."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from manuallabor.cli import app
from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import Task
from manuallabor.contracts.io import write_json
from manuallabor.jobs import graph, preflight
from manuallabor.jobs.executor import Plan, execute
from manuallabor.jobs.runner import JobRunner
from manuallabor.jobs.worker import run_job
from manuallabor.project import ProjectPaths
from manuallabor.providers import ProviderSet
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store
from tests.jobs.test_failed_stage import REFUSED, _providers
from tests.jobs.test_runner import job_lines, wait_for


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def sentence(host: str) -> str:
    return f"Ollama is not running at {host}. Start it (`ollama serve`) and press Retry."


def ollama(model: str, base: str) -> ModelRef:
    return ModelRef(provider="ollama", model=model, api_base=base)


def with_ollama(paths: ProjectPaths, base: str, tasks: tuple[str, ...]) -> None:
    """Point the given tasks of the project at an Ollama on `base` (the rest stay mock)."""
    cfg = paths.load_config()
    models = cfg.models.model_dump(mode="json")
    for t in tasks:
        models[t] = ollama(f"m-{t}", base).model_dump(mode="json")
    write_json(
        paths.config, cfg.model_copy(update={"models": type(cfg.models).model_validate(models)})
    )


class Recorder:
    def __init__(self, up: bool) -> None:
        self.up = up
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bool:
        self.urls.append(url)
        return self.up


# -- what a plan needs ---------------------------------------------------------------------------


def test_tasks_per_node(lp: ProjectPaths, tmp_path: Path) -> None:
    cfg = lp.load_config()
    units = [(n, "clean") for n in ("parse", "figures", "score", "group", "clean", "score2")]
    got = preflight.plan_tasks(lp, cfg, units)
    assert set(got) == {Task.verifier, Task.embeddings, Task.grouping, Task.cleanup, Task.vision}
    assert got[Task.embeddings] == [("group", "clean")]
    assert got[Task.verifier] == [("score", "clean"), ("score2", "clean")]  # clean.json exists
    lp.doc("clean").clean.unlink()
    assert preflight.plan_tasks(lp, cfg, [("score", "clean")]) == {}  # a first pass: no verifier
    off = cfg.model_copy(
        update={"cleanup": cfg.cleanup.model_copy(update={"llm": "off", "describe": False})}
    )
    assert preflight.plan_tasks(lp, off, [("clean", "clean")]) == {}
    assert preflight.plan_tasks(lp, cfg, [("parse", "clean"), ("figures", "clean")]) == {}


# -- the check -----------------------------------------------------------------------------------


def _cfg(base: str) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "name": "p",
            "models": {
                "embeddings": ollama("nomic-embed-text", base).model_dump(),
                "grouping": ollama("llama3.2:1b", base).model_dump(),
                "cleanup": {"provider": "anthropic", "model": "claude-x"},
                "verifier": {"provider": "mock", "model": "mock-verifier"},
            },
        }
    )


def test_an_unreachable_host_is_named_and_only_it_is_contacted() -> None:
    base = "http://127.0.0.1:11435"
    rec = Recorder(up=False)
    u = preflight.check(
        _cfg(base), [Task.embeddings, Task.grouping, Task.cleanup, Task.verifier], get=rec
    )
    assert u is not None and u.host == base and u.message == sentence(base)
    assert set(u.tasks) == {"embeddings", "grouping"}
    assert rec.urls == [f"{base}/api/tags"]  # one host, once; the API provider is never called


def test_a_reachable_host_passes_and_no_ollama_task_contacts_nothing() -> None:
    rec = Recorder(up=True)
    assert preflight.check(_cfg("http://127.0.0.1:11435"), [Task.embeddings], get=rec) is None
    rec2 = Recorder(up=False)
    assert preflight.check(_cfg("http://127.0.0.1:11435"), [Task.cleanup], get=rec2) is None
    assert rec2.urls == []


def test_the_default_host_follows_ollama_host(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ProjectConfig.model_validate(
        {"name": "p", "models": {"embeddings": {"provider": "ollama", "model": "e"}}}
    )
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11999")
    rec = Recorder(up=False)
    u = preflight.check(cfg, [Task.embeddings], get=rec)
    assert u is not None and rec.urls == ["http://127.0.0.1:11999/api/tags"]


def test_a_closed_port_is_unreachable_with_the_real_client() -> None:
    base = f"http://127.0.0.1:{closed_port()}"
    u = preflight.check(_cfg(base), [Task.embeddings])
    assert u is not None and u.message == sentence(base)


def test_mock_mode_never_checks(lp: ProjectPaths) -> None:
    with_ollama(lp, f"http://127.0.0.1:{closed_port()}", ("embeddings", "grouping"))
    rec = Recorder(up=False)
    reach = preflight.reacher(lp, lp.load_config(), "mock", get=rec)
    assert reach is None and rec.urls == []


# -- the job ---------------------------------------------------------------------------------------


def _drop_groups(paths: ProjectPaths) -> None:
    for slug in paths.list_slugs():
        paths.doc(slug).groups.unlink()


def _job(paths: ProjectPaths, job_id: str, plan: dict[str, Any], kind: str = "run") -> None:
    p = paths.job_plan(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"kind": kind, "mode": "config", "plan": plan, "files": []}))


def test_a_worker_job_with_an_unreachable_host_runs_no_unit(lp: ProjectPaths) -> None:
    base = f"http://127.0.0.1:{closed_port()}"
    with_ollama(lp, base, ("embeddings", "grouping"))
    _drop_groups(lp)
    _job(lp, "job-000001", {"to": "group"})
    assert run_job(lp.root, "job-000001") == 1
    lines = job_lines(lp, "job-000001")
    assert not [o for o in lines if o.get("event") in ("unit_start", "unit_done")]
    end = lines[-1]
    assert end["event"] == "job_end" and end["status"] == "failed"
    assert end["error"] == sentence(base) and end["error_code"] == "provider_unreachable"
    cfg = lp.load_config()
    for slug in lp.list_slugs():
        rec = graph.load_stages(lp, slug).nodes["group"]
        assert (rec.status, rec.error, rec.code) == (
            "failed",
            sentence(base),
            "provider_unreachable",
        )
        st = next(s for s in graph.doc_node_states(lp, slug, cfg) if s.node == "group")
        assert (st.state, st.code, st.reason) == ("failed", "provider_unreachable", sentence(base))


def test_a_unit_failure_rechecks_and_stops_the_job(lp: ProjectPaths) -> None:
    from manuallabor.providers.base import ProviderUnavailable

    _drop_groups(lp)
    calls = [0]
    u = preflight.Unreachable(
        "http://127.0.0.1:11435", ("embeddings",), sentence("http://127.0.0.1:11435")
    )

    def reach(units: list[tuple[str, str]]) -> preflight.Unreachable | None:
        calls[0] += 1
        return None if calls[0] == 1 else u  # up at the start, down after the first failure

    down: ProviderSet = _providers(lp, ProviderUnavailable(REFUSED))
    lines: list[dict[str, Any]] = []
    res = execute(
        lp, Plan(units=[("group", "clean"), ("group", "scanned")], to="group"),
        emit=lines.append, providers=lambda: down, reach=reach,
    )  # fmt: skip
    assert res.unreachable == u and not res.ok
    assert res.error_message() == u.message
    assert [o["doc"] for o in lines if o.get("event") == "unit_done"] == ["clean"]
    for slug in ("clean", "scanned"):
        rec = graph.load_stages(lp, slug).nodes["group"]
        assert (rec.error, rec.code) == (u.message, "provider_unreachable")


def test_the_runner_stores_the_code_and_a_merged_row_takes_it(lp: ProjectPaths) -> None:
    base = f"http://127.0.0.1:{closed_port()}"
    with_ollama(lp, base, ("embeddings", "grouping"))
    _drop_groups(lp)
    store = Store.open(lp)
    runner = JobRunner(lp, store, mode="config")
    try:
        a = runner.enqueue(RunPlanIn(to="group"))
        b = runner.enqueue(RunPlanIn(to="group"))
        assert runner.get(b.id).status == "merged"
        runner.start()
        wait_for(lambda: runner.get(b.id).status not in ("queued", "running", "merged"), 120)
    finally:
        runner.stop()
    for j in (runner.get(a.id), runner.get(b.id)):
        assert (j.status, j.error, j.error_code) == (
            "failed",
            sentence(base),
            "provider_unreachable",
        )
    store.close()


def test_labor_run_exits_1_with_the_sentence(lp: ProjectPaths) -> None:
    base = f"http://127.0.0.1:{closed_port()}"
    with_ollama(lp, base, ("embeddings", "grouping"))
    _drop_groups(lp)
    r = CliRunner().invoke(app, ["run", str(lp.root), "--to", "group"])
    assert r.exit_code == 1
    assert sentence(base) in r.output
    assert '"stage":"group"' not in r.output.replace(" ", "")  # no stage ran


def test_an_agent_job_checks_the_agent_model(lp: ProjectPaths) -> None:
    rec = Recorder(up=False)
    cfg = lp.load_config()
    models = cfg.models.model_dump(mode="json")
    models["agent"] = ollama("qwen2.5:3b", "http://127.0.0.1:11435").model_dump(mode="json")
    cfg = cfg.model_copy(update={"models": type(cfg.models).model_validate(models)})
    reach: Callable[..., Any] | None = preflight.reacher(lp, cfg, "config", get=rec)
    assert reach is not None
    u = preflight.check_agent(cfg, get=rec)
    assert u is not None and u.tasks == ("agent",)
