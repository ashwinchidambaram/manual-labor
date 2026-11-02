"""Through the API: a manual that could not be read, outside the selection, neither locks the
export nor hides why it failed (design 07 sections 20 and 21, design 11 section 20.18)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from manuallabor.jobs import graph
from manuallabor.project import ProjectPaths
from manuallabor.state.models import SelectionOp
from manuallabor.state.store import Store
from tests.export.helpers import approve_queued
from tests.export.test_api import Env

DOWN = "Ollama is not running at http://127.0.0.1:11434. Start it (`ollama serve`) and press Retry."
STUCK = "scanned"


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def strand(env: Env) -> None:
    """`scanned` as if it had been added while the service was down: the reviewer left it out
    and its grouping failed (nothing written, design 07 section 19), so it was never cleaned."""
    ids = sorted(b for b in env.ctx.scope.get().selection.block_ids if f"-{STUCK}-" in b)
    env.ctx.scope.apply(SelectionOp(op="deselect", block_ids=ids, request_id="t-leave-out"))
    dp = env.paths.doc(STUCK)
    for f in (dp.groups, dp.clean, dp.attach, dp.describe):  # never grouped, so never cleaned
        f.unlink()
    st = graph.load_stages(env.paths, STUCK)
    st.record("group", "failed", None, DOWN, code="provider_unreachable")
    graph.save_stages(env.paths, STUCK, st)


def test_export_status_and_post_ignore_a_failed_manual_outside_the_selection(env: Env) -> None:
    strand(env)
    assert isinstance(env.ctx.store, Store)
    approve_queued(env.paths, env.ctx.store)
    c = env.client
    s = c.get("/api/export/status").json()
    assert s["not_ready"] == [] and s["unlocked"] is True and s["blockers"] == [], s
    r = c.post("/api/export", json={"request_id": "t-export"})
    assert r.status_code == 202, r.text


def test_sources_carry_the_reason_and_the_code(env: Env) -> None:
    strand(env)
    rows = {s["slug"]: s for s in env.client.get("/api/sources").json()}
    group = next(n for n in rows[STUCK]["nodes"] if n["node"] == "group")
    assert group == {
        "node": "group", "state": "failed", "reason": DOWN, "code": "provider_unreachable"
    }  # fmt: skip
    other = next(n for n in rows["clean"]["nodes"] if n["node"] == "group")
    assert other["state"] == "fresh" and other["code"] is None


def test_a_selected_manual_that_is_not_ready_still_locks(env: Env) -> None:
    env.paths.doc(STUCK).clean.unlink()  # still selected, never confirmed: in scope, not ready
    s = env.client.get("/api/export/status").json()
    assert s["not_ready"] == [STUCK] and s["unlocked"] is False, s
