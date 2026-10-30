"""Review F4, F5, F12 on the real services: the read endpoints the screens poll are served from
one cache keyed by file stats and the last action id. A poll with nothing changed re-derives
nothing; every write that changes an answer (a decision, a flag, an override, a selection op, a
rewritten stage file) is seen by the next read; the cached answers equal the uncached ones."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from manuallabor.api.app import create_app
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.export import pipeline as export_pipeline
from manuallabor.jobs import graph
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.scoring import pipeline as scoring_pipeline
from manuallabor.state import review as review_mod
from manuallabor.state.interfaces import AppServices
from manuallabor.state.review import ReviewService
from manuallabor.state.services import build_services
from manuallabor.state.store import Store


@pytest.fixture
def app(lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any]]:
    monkeypatch.setenv("MANUALLABOR_HOME", str(lp.root.parent / "home"))
    svc = build_services(lp, mode="mock", resume=False, clock=utc_now)
    try:
        yield TestClient(create_app(svc, dev=True)), svc
    finally:
        svc.store.close()


def _count_calls(monkeypatch: pytest.MonkeyPatch, owner: Any, name: str) -> list[int]:
    calls = [0]
    real = getattr(owner, name)

    def wrapped(*a: Any, **kw: Any) -> Any:
        calls[0] += 1
        return real(*a, **kw)

    monkeypatch.setattr(owner, name, wrapped)
    return calls


def _ok(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()


def _uncached_status(paths: ProjectPaths) -> dict[str, Any]:
    """`export_status` the way the CLI calls it: a fresh service, nothing cached."""
    s = Store.open(paths, readonly=True)
    try:
        return export_pipeline.export_status(paths, s).model_dump(mode="json")
    finally:
        s.close()


def _touch(p: os.PathLike[str]) -> None:
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def _queued_text_block(c: TestClient) -> str:
    q = _ok(c.get("/api/verify/queue?limit=50"))["items"]
    return str(next(i["block_id"] for i in q if i["type"] != "figure"))


def test_export_status_poll_is_cached_and_every_write_is_seen(
    app: tuple[TestClient, AppServices], lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, svc = app
    first = _ok(c.get("/api/export/status"))
    assert first == _uncached_status(lp)
    parts = _count_calls(monkeypatch, export_pipeline, "_status_parts")
    for _ in range(3):
        assert _ok(c.get("/api/export/status")) == first
    assert parts[0] == 0  # three polls with nothing changed: no re-derivation

    # a decision (an action) is seen by the next poll
    bid = _queued_text_block(c)
    _ok(c.post("/api/verify/actions", json={"kind": "approve", "block_id": bid, "request_id": "a"}))
    after = _ok(c.get("/api/export/status"))
    assert parts[0] == 1
    assert after["counts"]["approved"] == first["counts"]["approved"] + 1
    assert after == _uncached_status(lp)

    # a flag, an override and a selection op each move the action log
    flagged = _queued_text_block(c)
    body = {
        "kind": "flag",
        "block_id": flagged,
        "request_id": "f",
        "flag": {"category": "wrong_text"},
    }
    _ok(c.post("/api/verify/actions", json=body))
    st = _ok(c.get("/api/export/status"))
    assert st["open_flags"] == after["open_flags"] + 1 and st == _uncached_status(lp)
    _ok(c.post("/api/export/override", json={"reason": "ok", "request_id": "o"}))
    st = _ok(c.get("/api/export/status"))
    assert len(st["overrides"]) == 1 and st == _uncached_status(lp)
    sel = _ok(c.get("/api/scope/selection"))["selection"]["block_ids"]
    put = {"op": "deselect", "block_ids": sel[:10], "request_id": "s"}
    _ok(c.put("/api/scope/selection", json=put))
    st2 = _ok(c.get("/api/export/status"))
    assert st2["counts"]["in_scope"] <= st["counts"]["in_scope"] and st2 == _uncached_status(lp)

    # a stage file rewritten by a job (same bytes, new stats) is a miss, not a stale answer
    _ok(c.get("/api/export/status"))
    n = parts[0]
    _touch(lp.doc("clean").scores)
    assert _ok(c.get("/api/export/status")) == st2
    assert parts[0] == n + 1


def test_scope_blocks_are_served_from_the_machine_view_cache(
    app: tuple[TestClient, AppServices], lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _svc = app
    want = [
        {
            "doc_id": slug,
            "blocks": [
                {
                    "id": b.id,
                    "type": b.type.value,
                    "status": b.status.value,
                    "numeric": b.has_numeric_spec,
                }
                for b in scoring_pipeline.load_scored_blocks(lp, slug)
            ],
        }
        for slug in sorted(lp.list_slugs())
    ]
    loads = _count_calls(monkeypatch, scoring_pipeline, "load_scored_blocks")
    monkeypatch.setattr(
        "manuallabor.state.data.load_scored_blocks", scoring_pipeline.load_scored_blocks
    )
    assert _ok(c.get("/api/scope/blocks")) == want
    n = loads[0]
    assert _ok(c.get("/api/scope/blocks")) == want
    assert loads[0] == n  # the second read loads nothing
    _touch(lp.doc("scanned").scores)
    assert _ok(c.get("/api/scope/blocks")) == want
    assert loads[0] == n + 1  # only the touched document is re-read


def test_doc_figures_and_page_blocks_follow_a_decision(
    app: tuple[TestClient, AppServices], lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, svc = app
    figs = _ok(c.get("/api/docs/clean/figures"))
    assert figs and all(f["status"] in {s.value for s in BlockStatus} for f in figs)
    derives = _count_calls(monkeypatch, ReviewService, "_derive_doc_uncached")
    again = _ok(c.get("/api/docs/clean/figures"))
    assert again == figs and derives[0] == 0  # cached: no derivation for a repeated read
    target = next(f for f in figs if f["status"] in ("queued", "auto_approved"))
    body = {"kind": "approve", "block_id": target["block_id"], "request_id": "fig"}
    _ok(c.post("/api/verify/actions", json=body))
    derives[0] = 0  # the action's own outcome derives inside its transaction, uncached
    after = {f["figure_id"]: f["status"] for f in _ok(c.get("/api/docs/clean/figures"))}
    assert after[target["figure_id"]] == "approved"
    pages = sorted({f["record"]["page"] for f in figs})
    for page in pages:
        rows = _ok(c.get(f"/api/docs/clean/pages/{page}/blocks"))
        for f in figs:
            if f["record"]["page"] == page:
                got = next(r for r in rows if r["block_id"] == f["block_id"])["status"]
                assert got == after[f["figure_id"]]
    # one derivation of the document serves the figure list and every page after the write
    assert derives[0] == 1


def test_status_orphans_and_learning_are_cached_and_follow_writes(
    app: tuple[TestClient, AppServices], lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _svc = app
    first = _ok(c.get("/api/status"))
    assert all(d["orphaned_decisions"] == 0 for d in first["docs"])
    misses: list[str] = []
    real = graph._memo

    def counting(paths: ProjectPaths, slug: str, kind: str, sg: Any, make: Any) -> Any:
        def miss() -> Any:
            misses.append(f"{slug}:{kind}")
            return make()

        return real(paths, slug, kind, sg, miss)

    monkeypatch.setattr(graph, "_memo", counting)
    assert _ok(c.get("/api/status")) == first
    assert misses == []  # nothing re-read: documents, learning provenance, orphan counts
    # a decision on a block whose raw text then changes (a re-parse) is an orphan at once
    bid = _queued_text_block(c)
    _ok(c.post("/api/verify/actions", json={"kind": "approve", "block_id": bid, "request_id": "o"}))
    st = _ok(c.get("/api/status"))
    assert st["docs"] == first["docs"] and misses == [f"{d}:orphans" for d in lp.list_slugs()]
    slug = next(s for s in lp.list_slugs() if bid.startswith(f"b-{s}-"))
    p = lp.doc(slug).blocks
    raw = json.loads(p.read_text(encoding="utf-8"))
    for b in raw:
        if b["id"] == bid:
            b["raw_text"] += " (re-parsed)"
    p.write_text(json.dumps(raw), encoding="utf-8")
    st = _ok(c.get("/api/status"))
    assert next(d for d in st["docs"] if d["doc_id"] == slug)["orphaned_decisions"] == 1


def test_titles_lookup_matches_the_queue_cards(app: tuple[TestClient, AppServices]) -> None:
    c, _svc = app
    items = _ok(c.get("/api/verify/queue?limit=2000&view_threshold=1&sort=by_page"))["items"]
    pick = [items[5], items[0], items[-1], items[len(items) // 2]]
    ids = [i["block_id"] for i in pick]
    got = _ok(
        c.get("/api/verify/titles", params=[("ids", b) for b in [*ids, ids[0], "b-nope-p001-001"]])
    )
    assert [g["block_id"] for g in got] == ids  # asked order, once each, unknown left out
    for g, it in zip(got, pick, strict=True):
        assert g == {k: it[k] for k in ("block_id", "doc_id", "page", "type", "section_title")}
    assert c.get("/api/verify/titles").status_code == 422
    too_many = [("ids", "b-clean-p001-001")] * 201
    assert c.get("/api/verify/titles", params=too_many).status_code == 422


def test_titles_also_name_blocks_outside_the_queue(app: tuple[TestClient, AppServices]) -> None:
    """A flagged or approved blocker is not a queue card; it still gets its section."""
    c, svc = app
    assert isinstance(svc.review, ReviewService)
    blocks = svc.review.review_blocks("clean")
    heading_after = next(
        b for i, b in enumerate(blocks) if i > 0 and blocks[i - 1].type == BlockType.heading
    )
    _ok(
        c.post(
            "/api/verify/actions",
            json={"kind": "approve", "block_id": heading_after.id, "request_id": "t"},
        )
    )
    (row,) = _ok(c.get("/api/verify/titles", params={"ids": heading_after.id}))
    assert row["section_title"] and row["page"] == heading_after.page


def test_no_cache_inside_a_transaction(app: tuple[TestClient, AppServices]) -> None:
    _c, svc = app
    assert isinstance(svc.review, ReviewService)
    data = svc.review.data
    assert data.db_signature() is not None
    with svc.store.tx():
        assert data.db_signature() is None
    assert review_mod.ReviewService._doc_signature(svc.review, "clean") is not None
