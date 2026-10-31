"""The API end-to-end on the real services (not fakes), served by uvicorn on a copy of the
mock-scored two-document project: concurrent selection PUTs, request-id reuse and replays, and
the 30-action review sequence (persisted, replay-equal, cursor restored after a restart)."""

from __future__ import annotations

import re
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from manuallabor.api.app import create_app
from manuallabor.contracts.enums import FlagCategory
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.state.interfaces import AppServices
from manuallabor.state.models import Cursor, FlagIn, ReviewActionIn
from manuallabor.state.review import load_review_blocks
from manuallabor.state.services import build_services
from manuallabor.state.store import Store
from tests.state.helpers import Env


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@contextmanager
def serving(paths: ProjectPaths) -> Iterator[tuple[httpx.Client, AppServices]]:
    """Real services (job runner not started: jobs stay queued) behind uvicorn in a thread."""
    services = build_services(paths, mode="mock", resume=False, clock=utc_now)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(services, dev=True), host="127.0.0.1", port=port, log_level="error"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    t0 = time.monotonic()
    while not server.started:
        assert time.monotonic() - t0 < 30, "uvicorn did not start"
        time.sleep(0.02)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as c:
            yield c, services
    finally:
        server.should_exit = True
        t.join(timeout=30)
        services.store.close()


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


def _count(paths: ProjectPaths, kind: str | None = None) -> int:
    s = Store.open(paths, readonly=True)
    try:
        return sum(1 for a in s.iter_actions() if kind is None or a.kind.value == kind)
    finally:
        s.close()


def test_concurrent_selection_puts_are_all_applied(lp: ProjectPaths) -> None:
    with serving(lp) as (c, _svc):
        sel = c.get("/api/scope/selection").json()["selection"]["block_ids"]
        targets = sel[:20]
        assert len(targets) == 20
        before = _count(lp, "deselect")

        def deselect(i: int) -> int:
            r = c.put(
                "/api/scope/selection",
                json={"op": "deselect", "block_ids": [targets[i]], "request_id": f"cc{i}"},
            )
            return r.status_code

        with ThreadPoolExecutor(20) as ex:
            codes = list(ex.map(deselect, range(20)))
        assert codes == [200] * 20
        final = set(c.get("/api/scope/selection").json()["selection"]["block_ids"])
        assert [t for t in targets if t in final] == []  # no lost update
        assert set(sel) - set(targets) <= final
    assert _count(lp, "deselect") - before == 20


def test_request_id_reuse_is_409_and_replays_enqueue_nothing(lp: ProjectPaths) -> None:
    with serving(lp) as (c, _svc):
        q = c.get("/api/verify/queue?limit=20").json()["items"]
        bid = next(i["block_id"] for i in q if i["type"] != "figure")
        r = c.post(
            "/api/verify/actions", json={"kind": "approve", "block_id": bid, "request_id": "x1"}
        )
        assert r.status_code == 200
        r = c.put(
            "/api/scope/selection", json={"op": "select", "block_ids": [], "request_id": "x1"}
        )
        assert r.status_code == 409 and r.json()["code"] == "request_id_reused", r.text
        r = c.put(
            "/api/config/threshold", json={"value": 0.5, "reason": "slider", "request_id": "x1"}
        )
        assert r.status_code == 409 and r.json()["code"] == "request_id_reused"

        figs = c.get("/api/docs/clean/figures").json()
        fig = next(x for x in figs if x["attachments"])
        fid, art = fig["figure_id"], fig["attachments"][0]["article_id"]
        pb = c.get(f"/api/docs/clean/pages/{fig['record']['page']}/blocks").json()
        bb = next(x for x in pb if x["block_id"] == fig["block_id"])["bbox"]
        calls: list[tuple[str, str, dict[str, Any]]] = [
            ("POST", f"/api/figures/{fid}/detach", {"article_id": art, "request_id": "d1"}),
            ("POST", f"/api/figures/{fid}/attach", {"article_id": art, "request_id": "a1"}),
            (
                "PUT",
                f"/api/figures/{fid}/bbox",
                {"bbox": [bb[0] + 1, bb[1] + 1, bb[2] - 1, bb[3] - 1], "request_id": "b1"},
            ),
            (
                "PUT",
                "/api/config/threshold",
                {"value": 0.8, "reason": "slider", "request_id": "t1"},
            ),
        ]
        for method, url, body in calls:
            first = c.request(method, url, json=body)
            assert first.status_code in (200, 202), first.text
            n_jobs, n_actions = len(c.get("/api/jobs").json()), _count(lp)
            again = c.request(method, url, json=body)
            assert again.status_code == first.status_code
            assert again.json() == first.json()  # the original response, same job
            assert len(c.get("/api/jobs").json()) == n_jobs, url  # no second job
            assert _count(lp) == n_actions
        # an attach request id reused on another endpoint
        r = c.post(f"/api/figures/{fid}/detach", json={"article_id": art, "request_id": "t1"})
        assert r.status_code == 409 and r.json()["code"] == "request_id_reused"


def test_a_figure_reattach_burst_leaves_one_job(lp: ProjectPaths) -> None:
    """Design 07 section 18: the Verify picker's re-attach (attach here, then detach from every
    other article, one request each) queues one job; the others are merged rows that point at it
    and replay to their first responses."""
    with serving(lp) as (c, _svc):
        fid = target = None
        old: list[str] = []
        for slug in ("scanned", "clean"):
            figs = c.get(f"/api/docs/{slug}/figures").json()
            arts = sorted({a["article_id"] for f in figs for a in f["attachments"]})
            for f in figs:
                mine = [a["article_id"] for a in f["attachments"]]
                free = [a for a in arts if a not in mine]
                if mine and free:
                    fid, target, old = f["figure_id"], free[0], mine
                    break
            if fid:
                break
        assert fid and target and old, "no figure to move between articles"
        n0 = len(c.get("/api/jobs").json())
        detaches = [("detach", a, f"mv-d{i}") for i, a in enumerate(old)]
        burst = [("attach", target, "mv-a"), *detaches]
        first = {}
        for op, art, rid in burst:
            r = c.post(f"/api/figures/{fid}/{op}", json={"article_id": art, "request_id": rid})
            assert r.status_code == 202, r.text
            first[rid] = r.json()
        jobs = c.get("/api/jobs").json()[n0:]
        assert len(jobs) == len(burst)
        survivor = first["mv-a"]["job"]
        assert survivor["status"] == "queued"
        assert [j["id"] for j in c.get("/api/jobs?status=queued&status=running").json()] == [
            survivor["id"]
        ]
        for _op, _art, rid in burst[1:]:
            j = first[rid]["job"]
            assert j["status"] == "merged" and j["merged_into"] == survivor["id"], j
        for op, art, rid in burst:  # replays: the first response, no new job
            again = c.post(f"/api/figures/{fid}/{op}", json={"article_id": art, "request_id": rid})
            assert again.json() == first[rid]
        assert len(c.get("/api/jobs").json()) == n0 + len(burst)


def _disp(b: dict[str, Any]) -> str:
    return b["clean_text"] if b["clean_text"] is not None else b["raw_text"]


def test_thirty_action_review_sequence_end_to_end(lp: ProjectPaths, tmp_path: Path) -> None:
    replay_root = tmp_path / "replay"
    shutil.copytree(lp.root, replay_root, symlinks=True)
    log: list[tuple[str, int, Any]] = []

    with serving(lp) as (c, _svc):
        base = _count(lp)

        def do(rid: str, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
            r = c.request(method, url, json=body)
            assert r.status_code in (200, 202), (rid, r.status_code, r.text)
            log.append((rid, r.status_code, r.json()))
            return r.json()

        def act(rid: str, kind: str, bid: str | None = None, **kw: Any) -> Any:
            body = {"kind": kind, "block_id": bid, "request_id": rid, **kw}
            return do(rid, "POST", "/api/verify/actions", body)

        q = c.get("/api/verify/queue?limit=200").json()["items"]
        det = {i["block_id"]: c.get(f"/api/verify/blocks/{i['block_id']}").json() for i in q[:40]}
        text_ids = [i["block_id"] for i in q[:40] if i["type"] != "figure"]
        numeric = [
            b
            for b in text_ids
            if det[b]["block"]["has_numeric_spec"] and re.search(r"\d", _disp(det[b]["block"]))
        ]
        n_id = numeric[0]
        rest = [b for b in text_ids if b != n_id]
        q0, q1, q2, q3, q4, q5, q6, q7, q8 = rest[:9]
        q1_text = _disp(det[q1]["block"])
        m = re.search(r"\d+", q1_text)
        bad = (
            q1_text[: m.start()] + str(int(m.group()) + 1) + q1_text[m.end() :]
            if m
            else q1_text + " 99"
        )

        do("r01", "PUT", "/api/verify/cursor", {"sort": "worst_first", "request_id": "r01"})
        act("r02", "approve", q0)
        act("r03", "approve", n_id)
        act("r04", "edit", q2, text=_disp(det[q2]["block"]))
        r409 = c.post(
            "/api/verify/actions",
            json={"kind": "edit", "block_id": q1, "text": bad, "request_id": "x409"},
        )
        assert r409.status_code == 409 and r409.json()["code"] == "edit_conflict"
        act("r05", "edit", q1, text=bad, confirm_content_change=True)
        act("r06", "flag", q3, flag={"category": "wrong_text", "note": "n1"})
        act("r07", "skip", q4)
        act("r08", "back")
        act("r09", "back")
        act("r10", "approve", q3)
        f = act("r11", "flag", q5, flag={"category": "missing_figure"})["flag"]["id"]
        do("r12", "POST", f"/api/flags/{f}/resolve", {"resolution": "done", "request_id": "r12"})
        figs = c.get("/api/docs/clean/figures").json()
        fig = next(x for x in figs if x["attachments"])
        fid, art = fig["figure_id"], fig["attachments"][0]["article_id"]
        do("r13", "POST", f"/api/figures/{fid}/detach", {"article_id": art, "request_id": "r13"})
        do("r14", "POST", f"/api/figures/{fid}/attach", {"article_id": art, "request_id": "r14"})
        pb = c.get(f"/api/docs/clean/pages/{fig['record']['page']}/blocks").json()
        bb = next(x for x in pb if x["block_id"] == fig["block_id"])["bbox"]
        do(
            "r15",
            "PUT",
            f"/api/figures/{fid}/bbox",
            {"bbox": [bb[0] + 1, bb[1] + 1, bb[2] - 1, bb[3] - 1], "request_id": "r15"},
        )
        sel = c.get("/api/scope/selection").json()["selection"]
        used = set(text_ids[:12])
        two = [b for b in sel["block_ids"] if b.startswith("b-scanned") and b not in used][:2]
        assert len(two) == 2
        put = "/api/scope/selection"
        do("r16", "PUT", put, {"op": "deselect", "block_ids": two, "request_id": "r16"})
        do("r17", "PUT", put, {"op": "select", "block_ids": two, "request_id": "r17"})
        v0 = sel["active_view"]
        other = "structure" if v0 == "topic" else "topic"
        do("r18", "PUT", put, {"op": "set_view", "view": other, "request_id": "r18"})
        do("r19", "PUT", put, {"op": "set_view", "view": v0, "request_id": "r19"})
        do("r20", "PUT", put, {"op": "set_split", "split": "per_document", "request_id": "r20"})
        split = sel["article_split"]
        do("r21", "PUT", put, {"op": "set_split", "split": split, "request_id": "r21"})
        cur = "/api/verify/cursor"
        do("r22", "PUT", cur, {"sort": "worst_first", "view_threshold": 1.0, "request_id": "r22"})
        do("r23", "PUT", cur, {"sort": "worst_first", "view_threshold": None, "request_id": "r23"})
        do("r24", "PUT", "/api/learning", {"enabled": True, "request_id": "r24"})
        do("r25", "PUT", "/api/learning", {"enabled": False, "request_id": "r25"})
        act("r26", "approve", q6)
        act("r27", "skip", q7)
        act("r28", "edit", q8, text=_disp(det[q8]["block"]))
        g = c.get("/api/scope/groups?doc=clean").json()[0]["groups"]["topics"][0]
        do(
            "r29",
            "POST",
            "/api/scope/regroup",
            {
                "doc_id": "clean",
                "kind": "rename",
                "topic_slug": g["slug"],
                "title": "Renamed by review",
                "request_id": "r29",
            },
        )
        last = act("r30", "back")
        # a replay of an earlier request returns the stored outcome and writes nothing
        assert act("r02", "approve", q0) == next(x[2] for x in log if x[0] == "r02")
        live_cursor = c.get("/api/verify/cursor").json()
        assert live_cursor == last["cursor"]

    # every action persisted, in order, with monotonic ids
    s = Store.open(lp, readonly=True)
    try:
        rows = list(s.iter_actions())
        src_cursor = s.get_cursor()
    finally:
        s.close()
    new = rows[base:]
    assert [a.request_id for a in new] == [f"r{i:02d}" for i in range(1, 31)]
    ids = [a.id for a in rows]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)

    # replaying the review/cursor actions on a fresh copy derives the same statuses and cursor
    e = Env(ProjectPaths(replay_root))
    try:
        for a in new:
            k = a.kind.value
            if k in ("approve", "edit", "flag", "skip", "back"):
                kw: dict[str, Any] = {}
                if k == "edit":
                    kw = {"text": a.payload["text"], "confirm_content_change": True}
                if k == "flag":
                    assert a.example is not None
                    kw = {
                        "flag": FlagIn(
                            category=FlagCategory(a.example["flag_category"]),
                            note=a.example["flag_note"],
                        )
                    }
                e.review.act(
                    ReviewActionIn(
                        kind=k,  # type: ignore[arg-type]
                        block_id=None if k == "back" else a.target_id,
                        request_id=a.request_id or "",
                        **kw,
                    )
                )
            elif k == "resolve_flag":
                e.review.resolve_flag(
                    a.payload["flag_id"], a.payload["resolution"], a.request_id or ""
                )
            elif k in ("cursor", "threshold_view"):
                e.review.set_cursor(Cursor.model_validate(a.payload["cursor"]), a.request_id or "")
        s = Store.open(lp, readonly=True)
        try:
            for slug in lp.list_slugs():
                want = {
                    b.id: (b.status.value, b.clean_text, b.numbers_verified)
                    for b in load_review_blocks(lp, s, slug)
                }
                got = {
                    b.id: (b.status.value, b.clean_text, b.numbers_verified)
                    for b in load_review_blocks(e.paths, e.store, slug)
                }
                assert got == want, slug
        finally:
            s.close()
        assert e.store.get_cursor() == src_cursor
    finally:
        e.close()

    # the cursor is restored verbatim after a restart
    with serving(lp) as (c, _svc):
        assert c.get("/api/verify/cursor").json() == last["cursor"]
        n = _count(lp)
        assert act_replay(c, q6) == next(x[2] for x in log if x[0] == "r26")
        assert _count(lp) == n


def act_replay(c: httpx.Client, bid: str) -> Any:
    r = c.post(
        "/api/verify/actions", json={"kind": "approve", "block_id": bid, "request_id": "r26"}
    )
    assert r.status_code == 200
    return r.json()
