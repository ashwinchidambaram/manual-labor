"""E22: the export routes over a real project (real store, real job runner, in-process worker)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from manuallabor.api.app import create_app
from manuallabor.export.validate import validate_zip
from manuallabor.jobs.worker import run_job
from manuallabor.project import ProjectPaths
from manuallabor.state.interfaces import AppServices
from manuallabor.state.store import Store

NOW = "2026-10-29T12:00:00Z"


class Env:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.ctx = self.services(paths)
        self.client = TestClient(create_app(self.ctx))

    @staticmethod
    def services(paths: ProjectPaths) -> AppServices:
        """The module-7 services around a real store (independent of the agent wiring)."""
        from manuallabor.jobs.runner import JobRunner
        from manuallabor.state.data import ProjectData
        from manuallabor.state.figures import FigureService
        from manuallabor.state.learning import LearningService
        from manuallabor.state.review import ReviewService
        from manuallabor.state.scope import ScopeService

        store = Store.open(paths)
        data = ProjectData(paths, store)
        figures = FigureService(paths, store, data)
        return AppServices(
            paths=paths,
            store=store,
            review=ReviewService(paths, store, data, figures),
            scope=ScopeService(paths, store, data),
            figures=figures,
            learning=LearningService(paths, store),
            runner=JobRunner(paths, store, mode="mock", resume=False),
            mock=True,
        )

    def close(self) -> None:
        self.ctx.store.close()


@pytest.fixture
def unreviewed_env(unreviewed: ProjectPaths) -> Iterator[Env]:
    e = Env(unreviewed)
    yield e
    e.close()


def supervise(env: Env, job_id: str) -> None:
    """What the serve process's JobRunner does with a worker that has exited: read its log
    (handing events to their handlers) and finalize the row. Run twice: replay-safe."""
    store = env.ctx.store
    assert isinstance(store, Store)
    store.update_job(job_id, status="running", pid=None)
    env.ctx.runner.poll()
    assert env.ctx.runner.get(job_id).status == "done"
    from manuallabor.jobs.runner import _Tail

    env.ctx.runner._read(job_id, _Tail())  # an adopted job re-reads its log from the start


def export_runs(env: Env) -> list[dict[str, object]]:
    store = env.ctx.store
    assert isinstance(store, Store)
    return [a.payload for a in store.iter_actions() if a.kind.value == "export_run"]


def approve_everything(env: Env) -> None:
    from tests.export.helpers import approve_queued

    assert isinstance(env.ctx.store, Store)
    approve_queued(env.paths, env.ctx.store)


def test_e22_status_shape_and_the_locked_post(unreviewed_env: Env) -> None:
    c = unreviewed_env.client
    s = c.get("/api/export/status").json()
    assert set(s) == {
        "unlocked",
        "open_flags",
        "overrides",
        "queued",
        "blockers",
        "summary",
        "zip_path",
    }
    assert s["unlocked"] is False and s["queued"] > 0 and 0 < len(s["blockers"]) <= 20
    assert s["summary"] is None and s["zip_path"] is None and s["overrides"] == []
    r = c.post("/api/export")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "export_locked" and body["queued"] == s["queued"] and body["blockers"]
    assert c.get("/api/export/download").status_code == 404
    assert c.get("/api/export/download").json()["code"] == "no_export"


def test_e22_override_route_is_idempotent_and_validated(unreviewed_env: Env) -> None:
    c = unreviewed_env.client
    first = c.get("/api/export/status").json()["blockers"][0]
    assert (
        c.post(
            "/api/export/override", json={"reason": "r", "target_id": "b-no-p001-01"}
        ).status_code
        == 422
    )
    assert (
        c.post("/api/export/override", json={"reason": "r", "flag_id": "flag-000042"}).status_code
        == 422
    )
    body = {"reason": "waive one", "target_id": first, "request_id": "ov-1"}
    s1 = c.post("/api/export/override", json=body).json()
    s2 = c.post("/api/export/override", json=body).json()
    assert s1 == s2 and len(s1["overrides"]) == 1 and s1["overrides"][0]["target_id"] == first
    assert first not in s1["blockers"] and s1["unlocked"] is False
    store = unreviewed_env.ctx.store
    assert sum(1 for a in store.iter_actions() if a.kind.value == "export_override") == 1


def test_e22_post_runs_the_export_in_the_worker_and_download_matches(unreviewed_env: Env) -> None:
    env = unreviewed_env
    c = env.client
    approve_everything(env)
    s = c.get("/api/export/status").json()
    assert s["unlocked"] is True and s["blockers"] == [] and s["queued"] == 0
    r = c.post("/api/export")
    assert r.status_code == 202 and r.json()["kind"] == "export" and r.json()["status"] == "queued"
    job = r.json()
    assert c.post("/api/export").json()["id"] == job["id"]  # one export job at a time
    # run the job exactly as the supervisor's subprocess would (same code, same files)
    import os

    os.environ["MANUALLABOR_NOW"] = NOW
    try:
        assert run_job(env.paths.root, job["id"]) == 0
    finally:
        del os.environ["MANUALLABOR_NOW"]
    log = env.ctx.runner.log(job["id"], 0)
    stages = [(o["stage"], o["status"]) for o in log if "stage" in o]
    assert ("assemble", "built") in stages and ("export", "built") in stages
    assert export_runs(env) == []  # the worker has no DB access; the supervisor records it
    supervise(env, job["id"])
    runs = export_runs(env)
    assert len(runs) == 1, runs  # exactly one `export_run` action, even after a re-read
    assert any(o.get("event") == "unit_done" and o["node"] == "export" for o in log)
    st = c.get("/api/export/status").json()
    assert runs[0]["zip_sha256"] == st["summary"]["zip_sha256"]
    assert runs[0]["articles"] == st["summary"]["articles"] and runs[0]["overrides"] == 0
    assert st["summary"]["articles"] > 0 and st["zip_path"].endswith("project-a-kb.zip")
    assert st["summary"]["generated_at"] == NOW
    d = c.get("/api/export/download")
    assert d.status_code == 200 and d.headers["content-type"] == "application/zip"
    assert d.headers["X-Content-SHA256"] == hashlib.sha256(d.content).hexdigest()
    assert d.headers["X-Content-SHA256"] == st["summary"]["zip_sha256"]
    out = env.paths.root / "downloaded.zip"
    out.write_bytes(d.content)
    assert validate_zip(out) == []


def test_e22_unreviewed_blocks_can_go_out_with_a_blanket_override(unreviewed_env: Env) -> None:
    env = unreviewed_env
    c = env.client
    s = c.post(
        "/api/export/override", json={"reason": "ship it", "request_id": "ov-blanket"}
    ).json()
    assert s["blockers"] == [] and s["unlocked"] is False and len(s["overrides"]) == 1
    r = c.post("/api/export")
    assert r.status_code == 202
    import os

    os.environ["MANUALLABOR_NOW"] = NOW
    try:
        assert run_job(env.paths.root, r.json()["id"]) == 0
    finally:
        del os.environ["MANUALLABOR_NOW"]
    supervise(env, r.json()["id"])
    runs = export_runs(env)
    assert len(runs) == 1 and int(runs[0]["overrides"]) > 0  # type: ignore[call-overload]
    st = c.get("/api/export/status").json()
    assert st["summary"]["review"]["overrides"] > 0
    # the override was spent by this export: the gate is closed again, also for a second job
    assert st["overrides"] == [] and st["blockers"]
    assert c.post("/api/export").status_code == 409


def test_the_export_job_is_cancel_safe_when_blocked(unreviewed_env: Env) -> None:
    """A job queued while locked (e.g. reviews undone meanwhile) fails cleanly with the blockers."""
    env = unreviewed_env
    from manuallabor.state.models import RunPlanIn

    job = env.ctx.runner.enqueue(RunPlanIn(to="export"), kind="export")
    assert run_job(env.paths.root, job.id) == 1
    log = env.ctx.runner.log(job.id, 0)
    assert any(o.get("status") == "locked" and o.get("blockers") for o in log)
    assert not Path(env.paths.zip_path).exists() and not env.paths.assembled.exists()
