"""`GET /api/sources/{slug}/removal` and `DELETE /api/sources/{slug}` (design 07 section 22)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from manuallabor.project import ProjectPaths
from manuallabor.state.models import FlagIn, ReviewActionIn, RunPlanIn
from manuallabor.state.store import Store
from tests.export.test_api import Env
from tests.state.test_remove_source import own_sources

GONE = "scanned"


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    own_sources(lp)
    e = Env(lp)
    review = e.ctx.review
    item = review.queue(None, None, GONE, 1, 0).items[0]
    review.act(ReviewActionIn(kind="approve", block_id=item.block_id, request_id="t-a"))
    flagged = review.queue(None, None, GONE, 1, 0).items[0]
    review.act(
        ReviewActionIn(
            kind="flag",
            block_id=flagged.block_id,
            flag=FlagIn(category="wrong_text", note=None),  # type: ignore[arg-type]
            request_id="t-f",
        )
    )
    yield e
    e.close()


def test_preview_delete_replay_and_status(env: Env) -> None:
    c = env.client
    p = c.get(f"/api/sources/{GONE}/removal").json()
    assert p["doc_id"] == GONE and p["removed"] is False and p["blocked_by"] is None
    assert (p["decisions"], p["open_flags"], p["flags"]) == (2, 1, 1)
    r = c.delete(f"/api/sources/{GONE}", params={"request_id": "t-rm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] is True and body["decisions"] == 2
    assert [s["slug"] for s in c.get("/api/sources").json()] == ["clean"]
    sel = c.get("/api/scope/selection").json()["selection"]
    assert not [b for b in sel["block_ids"] if f"-{GONE}-" in b]
    summary = c.get("/api/scope/summary").json()
    assert summary["docs"] == 1 and summary["blocks"] == len(sel["block_ids"])
    status = c.get("/api/status").json()
    assert status["removed"] == [
        {"doc_id": GONE, "filename": "scanned.pdf", "orphaned_decisions": 2, "open_flags": 1}
    ]
    # replay: the first answer, nothing more; a new request for a removed manual: 404
    again = c.delete(f"/api/sources/{GONE}", params={"request_id": "t-rm"})
    assert again.status_code == 200 and again.json() == body
    assert c.delete(f"/api/sources/{GONE}", params={"request_id": "t-rm2"}).status_code == 404
    assert c.get(f"/api/sources/{GONE}/removal").status_code == 404
    # the flag on a removed block no longer counts toward the export gate
    assert c.get("/api/export/status").json()["open_flags"] == 0


def test_delete_is_refused_while_a_job_covers_the_manual(env: Env) -> None:
    store = env.ctx.store
    assert isinstance(store, Store)
    store.add_job(kind="run", plan=RunPlanIn(to="score2").model_dump(mode="json"))
    p = env.client.get(f"/api/sources/{GONE}/removal").json()
    assert p["blocked_by"] and "job" in p["blocked_by"].lower()
    r = env.client.delete(f"/api/sources/{GONE}", params={"request_id": "t-rm"})
    assert r.status_code == 409 and r.json()["code"] == "job_active", r.text
    assert GONE in env.paths.list_slugs()


def test_delete_needs_a_request_id(env: Env) -> None:
    assert env.client.delete(f"/api/sources/{GONE}").status_code == 422
