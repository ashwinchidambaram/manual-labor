"""Module 12 backend: GET/PUT /api/ui/guide. UI state lives in `meta`; it is never an action
and never reaches decisions, learning or any other table."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from manuallabor.api.app import create_app
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.state.interfaces import AppServices
from manuallabor.state.services import build_services
from tests.api.conftest import Env

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


@contextmanager
def opened(paths: ProjectPaths) -> Iterator[tuple[TestClient, AppServices]]:
    """The real services (job runner not started) behind the app; closing = server stop."""
    svc = build_services(paths, mode="mock", resume=False, clock=utc_now)
    try:
        yield TestClient(create_app(svc, dev=True)), svc
    finally:
        svc.store.close()


def non_meta_dump(paths: ProjectPaths) -> dict[str, list[tuple[Any, ...]]]:
    conn = sqlite3.connect(f"file:{paths.db}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'meta' ORDER BY name"
            )
        ]
        return {n: conn.execute(f"SELECT * FROM {n} ORDER BY 1").fetchall() for n in names}  # noqa: S608
    finally:
        conn.close()


def count_actions(paths: ProjectPaths) -> int:
    conn = sqlite3.connect(f"file:{paths.db}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0])
    finally:
        conn.close()


def test_guide_defaults_to_unseen(lp: ProjectPaths) -> None:
    with opened(lp) as (c, _):
        r = c.get("/api/ui/guide")
        assert r.status_code == 200
        assert r.json() == {"seen": False, "seen_at": None, "version": 1}


def test_guide_seen_persists_across_a_restart(lp: ProjectPaths) -> None:
    with opened(lp) as (c, _):
        r = c.put("/api/ui/guide", json={"seen": True})
        assert r.status_code == 200
        first = r.json()
        assert first["seen"] is True and first["seen_at"] and first["version"] == 1
    with opened(lp) as (c, _):
        assert c.get("/api/ui/guide").json() == first


def test_guide_put_false_resets(lp: ProjectPaths) -> None:
    with opened(lp) as (c, _):
        c.put("/api/ui/guide", json={"seen": True})
        r = c.put("/api/ui/guide", json={"seen": False})
        assert r.json() == {"seen": False, "seen_at": None, "version": 1}
    with opened(lp) as (c, _):
        assert c.get("/api/ui/guide").json()["seen"] is False


def test_guide_version_bump_shows_the_guide_again(lp: ProjectPaths) -> None:
    with opened(lp) as (c, svc):
        svc.store.set_meta("ui.guide_seen", '{"seen_at": "2026-01-01T00:00:00Z", "version": 0}')
        assert c.get("/api/ui/guide").json() == {"seen": False, "seen_at": None, "version": 1}
        assert c.put("/api/ui/guide", json={"seen": True}).json()["seen"] is True
        got = c.get("/api/ui/guide").json()
        assert got["seen"] is True and got["seen_at"] and got["version"] == 1


def test_guide_put_is_not_an_action_and_touches_no_other_table(lp: ProjectPaths) -> None:
    with opened(lp) as (c, svc):
        decisions_before = c.get("/api/decisions/export").text
        learning_before = svc.learning.state().model_dump_json()
    before_actions = count_actions(lp)
    before = non_meta_dump(lp)
    with opened(lp) as (c, svc):
        assert c.put("/api/ui/guide", json={"seen": True}).status_code == 200
        assert c.put("/api/ui/guide", json={"seen": False}).status_code == 200
        assert c.put("/api/ui/guide", json={"seen": True}).status_code == 200
        assert c.get("/api/decisions/export").text == decisions_before
        assert svc.learning.state().model_dump_json() == learning_before
    assert count_actions(lp) == before_actions
    assert non_meta_dump(lp) == before


@pytest.mark.parametrize("body", [{}, {"seen": "maybe"}, {"seen": None}, {"seen": True, "x": 1}])
async def test_guide_put_rejects_bad_bodies(env: Env, body: dict[str, Any]) -> None:
    async with env.client() as api:
        r = await api.put("/api/ui/guide", json=body)
        assert r.status_code == 422
        assert r.json()["code"] == "validation_error"
        assert (await api.get("/api/ui/guide")).json()["seen"] is False


async def test_guide_roundtrip_on_the_fake_services(env: Env) -> None:
    async with env.client() as api:
        assert (await api.put("/api/ui/guide", json={"seen": True})).json()["seen"] is True
        assert (await api.get("/api/ui/guide")).json()["seen"] is True
