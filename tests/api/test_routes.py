"""A1 route coverage, A2 project/status/probe, A8 jobs, A10 stubs, A11 export, A14 non-blocking."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute
from pydantic import TypeAdapter

from manuallabor.api.app import create_app
from tests.api.conftest import Env
from tests.api.fakes import FIG, bid

pytestmark = pytest.mark.anyio

RID = {"request_id": "r-1"}
BBOX = {"bbox": [0, 0, 50, 50], "request_id": "r-1"}

# (method, path template) -> (url, request kwargs, expected status)
CASES: dict[tuple[str, str], tuple[str, dict[str, Any], int]] = {
    ("GET", "/api/project"): ("/api/project", {}, 200),
    ("GET", "/api/status"): ("/api/status", {}, 200),
    ("GET", "/api/probe"): ("/api/probe", {}, 404),
    ("POST", "/api/probe"): ("/api/probe", {}, 200),
    ("POST", "/api/config/apply-tier"): (
        "/api/config/apply-tier",
        {"json": {"tier": "small", "force": True}},
        404,
    ),
    ("PUT", "/api/config/threshold"): (
        "/api/config/threshold",
        {"json": {"value": 0.9, "reason": "slider"}},
        200,
    ),
    ("GET", "/api/sources"): ("/api/sources", {}, 200),
    ("POST", "/api/sources"): (
        "/api/sources",
        {"files": [("files", ("a.pdf", b"%PDF-1", "application/pdf"))]},
        202,
    ),
    ("GET", "/api/docs/{slug}/source"): ("/api/docs/doc/source", {}, 200),
    ("GET", "/api/docs/{slug}/pages/{page}.png"): ("/api/docs/doc/pages/1.png?dpi=100", {}, 200),
    ("GET", "/api/docs/{slug}/pages/{page}/blocks"): ("/api/docs/doc/pages/1/blocks", {}, 200),
    ("GET", "/api/scope/groups"): ("/api/scope/groups", {}, 200),
    ("GET", "/api/scope/blocks"): ("/api/scope/blocks", {}, 200),
    ("GET", "/api/scope/selection"): ("/api/scope/selection", {}, 200),
    ("PUT", "/api/scope/selection"): (
        "/api/scope/selection",
        {"json": {"op": "select", "block_ids": [bid(1)], "request_id": "r"}},
        200,
    ),
    ("GET", "/api/scope/summary"): ("/api/scope/summary", {}, 200),
    ("POST", "/api/scope/regroup"): (
        "/api/scope/regroup",
        {
            "json": {
                "doc_id": "doc",
                "kind": "move",
                "block_id": bid(1),
                "to_topic_slug": "t",
                "request_id": "r",
            }
        },
        202,
    ),
    ("GET", "/api/scope/models"): ("/api/scope/models", {}, 200),
    ("POST", "/api/scope/confirm"): ("/api/scope/confirm", {"json": RID}, 202),
    ("GET", "/api/verify/queue"): ("/api/verify/queue", {}, 200),
    ("GET", "/api/verify/cursor"): ("/api/verify/cursor", {}, 200),
    ("PUT", "/api/verify/cursor"): ("/api/verify/cursor", {"json": {"sort": "by_page"}}, 200),
    ("GET", "/api/verify/blocks/{block_id}"): (f"/api/verify/blocks/{bid(1)}", {}, 200),
    ("POST", "/api/verify/actions"): (
        "/api/verify/actions",
        {"json": {"kind": "approve", "block_id": bid(1), "request_id": "r"}},
        200,
    ),
    ("GET", "/api/flags"): ("/api/flags", {}, 200),
    ("POST", "/api/flags/{flag_id}/resolve"): (
        "/api/flags/flag-000001/resolve",
        {"json": {"resolution": "ok"}},
        404,
    ),
    ("GET", "/api/articles/{article_id}/figures"): ("/api/articles/doc/figures", {}, 200),
    ("GET", "/api/docs/{slug}/figures"): ("/api/docs/doc/figures", {}, 200),
    ("GET", "/api/figures/{fid}/image"): (f"/api/figures/{FIG}/image", {}, 200),
    ("POST", "/api/figures/{fid}/attach"): (
        f"/api/figures/{FIG}/attach",
        {"json": {"article_id": "doc"}},
        202,
    ),
    ("POST", "/api/figures/{fid}/detach"): (
        f"/api/figures/{FIG}/detach",
        {"json": {"article_id": "doc"}},
        202,
    ),
    ("PUT", "/api/figures/{fid}/bbox"): (f"/api/figures/{FIG}/bbox", {"json": BBOX}, 202),
    ("GET", "/api/decisions/export"): ("/api/decisions/export", {}, 200),
    ("GET", "/api/learning"): ("/api/learning", {}, 200),
    ("PUT", "/api/learning"): ("/api/learning", {"json": {"enabled": True}}, 200),
    ("GET", "/api/learning/snapshots"): ("/api/learning/snapshots", {}, 200),
    ("POST", "/api/learning/snapshots"): ("/api/learning/snapshots", {}, 200),
    ("POST", "/api/learning/activate/{snapshot_id}"): ("/api/learning/activate/001", {}, 404),
    ("POST", "/api/learning/rollback/{snapshot_id}"): ("/api/learning/rollback/001", {}, 404),
    ("POST", "/api/learning/reset"): ("/api/learning/reset", {}, 200),
    ("POST", "/api/learning/items/{item_id}/disable"): (
        "/api/learning/items/ex-1/disable",
        {},
        200,
    ),
    ("POST", "/api/learning/publish/{snapshot_id}"): ("/api/learning/publish/001", {}, 404),
    ("POST", "/api/jobs"): ("/api/jobs", {"json": {"to": "group"}}, 202),
    ("GET", "/api/jobs"): ("/api/jobs", {}, 200),
    ("GET", "/api/jobs/{job_id}"): ("/api/jobs/job-000001", {}, 404),
    ("GET", "/api/jobs/{job_id}/log"): ("/api/jobs/job-000001/log", {}, 404),
    ("POST", "/api/jobs/{job_id}/cancel"): ("/api/jobs/job-000001/cancel", {}, 404),
    ("POST", "/api/agent/run"): ("/api/agent/run", {}, 501),
    ("GET", "/api/agent/proposals"): ("/api/agent/proposals", {}, 501),
    ("POST", "/api/agent/proposals/{proposal_id}/accept"): (
        "/api/agent/proposals/prop-000001/accept",
        {},
        501,
    ),
    ("POST", "/api/agent/proposals/{proposal_id}/edit"): (
        "/api/agent/proposals/prop-000001/edit",
        {"json": {"text": "x"}},
        501,
    ),
    ("POST", "/api/agent/proposals/{proposal_id}/reject"): (
        "/api/agent/proposals/prop-000001/reject",
        {},
        501,
    ),
    ("POST", "/api/agent/accept-all-passing"): ("/api/agent/accept-all-passing", {}, 501),
    ("GET", "/api/calibration"): ("/api/calibration", {}, 501),
    ("POST", "/api/calibration/apply"): (
        "/api/calibration/apply",
        {"json": {"threshold": 0.8}},
        501,
    ),
    ("GET", "/api/export/status"): ("/api/export/status", {}, 200),
    ("POST", "/api/export"): ("/api/export", {}, 501),
    ("POST", "/api/export/override"): ("/api/export/override", {"json": {"reason": "r"}}, 501),
}


ROUTER_MODULES = [
    "project",
    "sources",
    "scope",
    "verify",
    "figures",
    "jobs",
    "learning",
    "agent",
    "export",
]


def api_route_objects() -> list[APIRoute]:
    import importlib

    out: list[APIRoute] = []
    for m in ROUTER_MODULES:
        router = importlib.import_module(f"manuallabor.api.routers.{m}").router
        out += [r for r in router.routes if isinstance(r, APIRoute)]
    return out


def api_routes(app: Any) -> set[tuple[str, str]]:
    """Every (method, path) the app serves, read from its OpenAPI document (FastAPI 0.16x keeps
    included routers lazy, so `app.routes` no longer lists them)."""
    return {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}


def test_a1_case_table_is_complete(env: Env) -> None:
    served = api_routes(env.app())
    declared = {(m, r.path) for r in api_route_objects() for m in r.methods or ()}
    assert served == declared == set(CASES)


@pytest.mark.parametrize("key", sorted(CASES), ids=lambda k: f"{k[0]} {k[1]}")
async def test_a1_route_status_and_body_validates(env: Env, key: tuple[str, str]) -> None:
    app = env.app()
    route = next(r for r in api_route_objects() if r.path == key[1] and key[0] in (r.methods or ()))
    url, kw, expected = CASES[key]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.request(key[0], url, **kw)
    assert r.status_code == expected, r.text
    if expected in (200, 202):
        if route.response_model is not None:
            TypeAdapter(route.response_model).validate_python(r.json())
    else:
        body = r.json()
        assert set(body) >= {"detail", "code"}
        assert isinstance(body["detail"], str)
        if expected == 501:
            assert body["code"] == "not_implemented"


async def test_a2_project_status_probe(env: Env, api: httpx.AsyncClient) -> None:
    p = (await api.get("/api/project")).json()
    assert p["name"] and p["mock"] is True and p["learning"]["enabled"] is False
    assert p["config"]["schema_version"] == "1.0"
    s = (await api.get("/api/status")).json()
    assert s["docs"][0]["doc_id"] == "doc"
    assert (await api.get("/api/probe")).status_code == 404
    post = await api.post("/api/probe")
    assert post.status_code == 200 and post.json()["suggestions"]["rows"]
    got = await api.get("/api/probe")
    assert got.status_code == 200 and got.json()["probe"] == post.json()["probe"]
    assert (env.paths.root / "probe.json").is_file()
    src = (await api.get("/api/sources")).json()
    assert src[0]["slug"] == "doc" and src[0]["ocr_warning"]
    assert src[0]["nodes"][1]["state"] == "stale"


async def test_apply_tier_and_threshold(env: Env, api: httpx.AsyncClient) -> None:
    await api.post("/api/probe")
    r = await api.post("/api/config/apply-tier", json={"tier": "small", "force": True})
    assert r.status_code == 200, r.text
    assert r.json()["models"]["cleanup"]["provider"] == "ollama"
    assert [n["node"] for n in r.json()["stale"]] == ["clean"]
    t = await api.put("/api/config/threshold", json={"value": 0.7, "reason": "calibration"})
    assert t.json()["threshold"] == 0.7 and t.json()["job"]["status"] == "queued"
    assert env.st.enqueued[-1][1].to == "score2"
    bad = await api.put("/api/config/threshold", json={"value": 7})
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"


async def test_page_and_source_and_upload(env: Env, api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/docs/doc/source")).content.startswith(b"%PDF")
    assert (await api.get("/api/docs/nope/source")).status_code == 404
    assert (await api.get("/api/docs/doc/pages/1.png")).headers["content-type"] == "image/png"
    assert (await api.get("/api/docs/doc/pages/1.png?dpi=5")).status_code == 422
    files = [("files", ("../evil.pdf", b"%PDF-x", "application/pdf"))]
    r = await api.post("/api/sources", files=files)
    assert r.status_code == 202
    kind, plan, saved = env.st.enqueued[-1]
    assert kind == "ingest_run" and plan.to == "group"
    assert saved[0].name == "evil.pdf" and env.paths.uploads in saved[0].parents
    assert saved[0].read_bytes() == b"%PDF-x"


async def test_a8_jobs(env: Env, api: httpx.AsyncClient) -> None:
    r = await api.post("/api/jobs", json={"to": "group", "docs": ["doc"], "force": ["figures"]})
    assert r.status_code == 202
    jid = r.json()["id"]
    assert r.json()["plan"]["docs"] == ["doc"]
    assert (await api.get(f"/api/jobs/{jid}")).json()["status"] == "queued"
    assert len((await api.get("/api/jobs")).json()) == 1
    assert (await api.get("/api/jobs?status=running")).json() == []
    log = (await api.get(f"/api/jobs/{jid}/log?after=1")).json()
    assert log == [{"event": "job_end", "status": "done"}]
    assert (await api.post(f"/api/jobs/{jid}/cancel")).json()["status"] == "cancelled"
    assert (await api.get("/api/jobs/job-999999")).status_code == 404


async def test_a10_stubs_and_export_status(env: Env, api: httpx.AsyncClient) -> None:
    for method, url in [
        ("POST", "/api/agent/run"),
        ("GET", "/api/agent/proposals"),
        ("GET", "/api/calibration"),
        ("POST", "/api/export"),
    ]:
        r = await api.request(method, url)
        assert r.status_code == 501 and r.json()["code"] == "not_implemented"
    s = (await api.get("/api/export/status")).json()
    assert s == {"unlocked": True, "open_flags": 0, "overrides": []}
    env.st.open_flags = 2
    s = (await api.get("/api/export/status")).json()
    assert s["unlocked"] is False and s["open_flags"] == 2


async def test_a11_decisions_export(env: Env, api: httpx.AsyncClient) -> None:
    for i in (1, 2, 3):
        await api.post(
            "/api/verify/actions",
            json={"kind": "approve", "block_id": bid(i, 1 if i < 3 else 2), "request_id": f"r{i}"},
        )
    r = await api.get("/api/decisions/export")
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = r.text.splitlines()
    rows = [json.loads(x) for x in lines]
    assert len(rows) == len(env.st.actions) == 3
    assert [x["id"] for x in rows] == sorted(x["id"] for x in rows)
    for raw, row in zip(lines, rows, strict=True):
        assert raw == json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def test_a14_non_blocking(env: Env, api: httpx.AsyncClient) -> None:
    env.st.job_delay = 1.0
    t0 = time.perf_counter()
    r = await api.post("/api/jobs", json={})
    assert r.status_code == 202
    await asyncio.sleep(0.05)
    assert env.st.jobs[r.json()["id"]].status == "running"
    for _ in range(5):
        t = time.perf_counter()
        q = await api.get("/api/verify/queue")
        assert q.status_code == 200 and time.perf_counter() - t < 0.2
    assert time.perf_counter() - t0 < 0.9  # the job was still running throughout
    for heavy in ("litellm", "docling", "torch"):
        assert heavy not in sys.modules, heavy


async def test_no_project_is_503() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="http://t"
    ) as c:
        r = await c.get("/api/project")
    assert r.status_code == 503 and r.json()["code"] == "no_project"


async def test_scope_blocks_g1(
    env: Env, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/scope/blocks lists scored docs only, with type/status/numeric per block."""
    from manuallabor.contracts.block import Block
    from manuallabor.contracts.enums import BlockStatus, BlockType
    from manuallabor.scoring import pipeline

    assert (await api.get("/api/scope/blocks")).json() == []  # no scores.json yet
    env.paths.doc("doc").scores.write_text("{}")
    blk = Block.model_construct(
        id=bid(1), type=BlockType.figure, status=BlockStatus.queued, has_numeric_spec=True
    )
    monkeypatch.setattr(pipeline, "load_scored_blocks", lambda paths, slug: [blk])
    r = await api.get("/api/scope/blocks")
    assert r.json() == [
        {
            "doc_id": "doc",
            "blocks": [{"id": bid(1), "type": "figure", "status": "queued", "numeric": True}],
        }
    ]
    assert (await api.get("/api/scope/blocks?doc=other")).json() == []
