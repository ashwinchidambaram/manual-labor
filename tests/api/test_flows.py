"""A3 scope, A4 keyboard flow, A5 edit 409, A6 threshold, A7 figures, A9 learning."""

# ruff: noqa: E501

from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import Env
from tests.api.fakes import FIG, bid

pytestmark = pytest.mark.anyio


async def act(api: httpx.AsyncClient, kind: str, n: int | None, page: int = 1, **kw: object):  # type: ignore[no-untyped-def]
    body: dict[str, object] = {"kind": kind, "request_id": f"r-{kind}-{n}-{page}-{kw}", **kw}
    if n is not None:
        body["block_id"] = bid(n, page)
    r = await api.post("/api/verify/actions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_a3_scope(env: Env, api: httpx.AsyncClient) -> None:
    r = await api.put(
        "/api/scope/selection",
        json={"op": "select_group", "group_id": "doc--g", "subtree": True, "request_id": "a"},
    )
    assert r.status_code == 200
    ids_ = r.json()["selection"]["block_ids"]
    assert ids_ == [bid(1), bid(2), bid(3)]
    assert r.json()["coverage"][0]["selected"] == 3 and r.json()["summary"]["blocks"] == 3
    v = await api.put(
        "/api/scope/selection", json={"op": "set_view", "view": "structure", "request_id": "b"}
    )
    assert v.json()["selection"]["block_ids"] == ids_
    assert v.json()["selection"]["active_view"] == "structure"
    # persists across a new app instance
    async with env.client() as again:
        g = (await again.get("/api/scope/selection")).json()
    assert g["selection"]["block_ids"] == ids_
    bad = await api.put("/api/scope/selection", json={"op": "bogus", "request_id": "x"})
    assert bad.status_code == 422
    rg = await api.post(
        "/api/scope/regroup",
        json={
            "doc_id": "doc",
            "kind": "rename",
            "topic_slug": "t",
            "title": "T",
            "request_id": "c",
        },
    )
    assert rg.status_code == 202 and rg.json()["override"]["kind"] == "rename"
    _, plan, _ = env.st.enqueued[-1]
    assert (plan.to, plan.docs) == ("group", ["doc"])
    conf = await api.post("/api/scope/confirm", json={"request_id": "d"})
    assert env.st.enqueued[-1][1].to == "score2" and conf.json()["kind"] == "run"


async def test_a4_keyboard_flow(env: Env, api: httpx.AsyncClient) -> None:
    q = (await api.get("/api/verify/queue")).json()
    assert [i["block_id"] for i in q["items"]] == [
        bid(n, p) for n, p in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3)]
    ]
    assert q["cursor"]["current_block_id"] == bid(1)
    # (action, block, page) -> expected next block
    script = [
        ("approve", 1, 1, bid(2, 1)),
        ("approve", 2, 1, bid(3, 2)),
        ("edit", 3, 2, bid(4, 2)),
        ("flag", 4, 2, bid(5, 3)),
        ("skip", 5, 3, bid(6, 3)),
        ("approve", 6, 3, bid(5, 3)),  # wraps to the skipped block
    ]
    for kind, n, page, expected in script:
        extra: dict[str, object] = {}
        if kind == "edit":
            extra["text"] = "Torque to 35 Nm."
        if kind == "flag":
            extra["flag"] = {"category": "wrong_text"}
        out = await act(api, kind, n, page, **extra)
        assert out["next"]["block_id"] == expected, (kind, n)
        assert out["cursor"]["current_block_id"] == expected
        assert out["action_id"] >= 1
    back = await act(api, "back", None)
    assert back["cursor"]["current_block_id"] == bid(6, 3) and len(back["cursor"]["trail"]) == 5
    last = await act(api, "approve", 5, 3)
    assert last["next"] is None and last["counts"]["pending"] == 0
    # idempotent replay
    again = await api.post(
        "/api/verify/actions",
        json={"kind": "approve", "block_id": bid(5, 3), "request_id": "r-approve-5-3-{}"},
    )
    assert again.json() == last
    n_actions = len(env.st.actions)
    assert n_actions == 8
    async with env.client() as c2:
        cur = (await c2.get("/api/verify/cursor")).json()
    assert cur == last["cursor"]
    dec = (await api.get("/api/decisions/export")).text.splitlines()
    assert len(dec) == n_actions
    detail = (await api.get(f"/api/verify/blocks/{bid(1)}")).json()
    assert detail["block"]["id"] == bid(1) and detail["page"]["source_url"]
    assert (await api.get("/api/verify/blocks/b-doc-p009-09")).status_code == 404
    assert (await api.get(f"/api/verify/blocks/{bid(9, 9)}")).status_code == 404


async def test_a4_back_with_empty_trail(env: Env, api: httpx.AsyncClient) -> None:
    out = await act(api, "back", None)
    assert out["cursor"]["current_block_id"] == bid(1) and out["cursor"]["trail"] == []


async def test_a5_edit_conflict_then_confirm(env: Env, api: httpx.AsyncClient) -> None:
    body = {"kind": "edit", "block_id": bid(1), "text": "Torque to 36 Nm.", "request_id": "e1"}
    r = await api.post("/api/verify/actions", json=body)
    assert r.status_code == 409
    j = r.json()
    assert j["code"] == "edit_conflict" and j["conflict"]["numeric_changes"] == ["35 → 36"]
    assert "diff" in j["conflict"] and "violations" in j["conflict"]
    assert env.st.actions == []
    ok = await api.post(
        "/api/verify/actions", json={**body, "confirm_content_change": True, "request_id": "e2"}
    )
    assert ok.status_code == 200
    assert ok.json()["decision"]["decision"]["edited_text"] == "Torque to 36 Nm."
    assert ok.json()["block_status"] == "edited"
    assert (await api.post("/api/verify/actions", json={"kind": "edit"})).status_code == 422


async def test_a6_threshold_is_a_view_filter(env: Env, api: httpx.AsyncClient) -> None:
    base = (await api.get("/api/verify/queue")).json()
    wide = (await api.get("/api/verify/queue?view_threshold=1.0")).json()
    assert wide["total"] == base["total"] + 1 and wide["items"][-1]["block_id"] == bid(1, 4)
    zero = (await api.get("/api/verify/queue?view_threshold=0.0")).json()
    assert zero["total"] == base["total"]  # machine-queued blocks stay listed
    assert env.st.actions == [] and env.st.decided == {}
    r = await api.put("/api/verify/cursor", json={"sort": "worst_first", "view_threshold": 1.0})
    assert r.json()["view_threshold"] == 1.0
    assert env.st.threshold_history == [(None, 1.0)]
    assert (await api.get("/api/verify/queue")).json()["total"] == base["total"] + 1
    assert (await api.get("/api/verify/queue?view_threshold=2")).status_code == 422
    paged = (await api.get("/api/verify/queue?limit=2&offset=1&sort=by_page")).json()
    assert [i["page"] for i in paged["items"]] == [1, 2] and paged["total"] == 7
    assert env.st.decided == {}


async def test_flags_resolve(env: Env, api: httpx.AsyncClient) -> None:
    await act(api, "flag", 1, flag={"category": "wrong_text", "note": "n"})
    flags = (await api.get("/api/flags")).json()
    assert len(flags) == 1 and flags[0]["status"] == "open"
    r = await api.post(f"/api/flags/{flags[0]['id']}/resolve", json={"resolution": "fixed"})
    assert r.json()["status"] == "resolved" and r.json()["resolution"] == "fixed"
    assert (await api.get("/api/flags")).json() == []
    assert len((await api.get("/api/flags?status=resolved")).json()) == 1
    assert (await api.get("/api/export/status")).json()["unlocked"] is True


async def test_a7_figures(env: Env, api: httpx.AsyncClient) -> None:
    rail = (await api.get("/api/articles/doc/figures")).json()
    assert rail[0]["figure_id"] == FIG and rail[0]["record"]["id"] == FIG
    img = await api.get(rail[0]["image_url"])
    assert img.headers["content-type"] == "image/png"
    a = await api.post(
        f"/api/figures/{FIG}/attach", json={"article_id": "doc", "anchor_block_id": bid(2)}
    )
    assert a.status_code == 202 and a.json()["override"]["op"] == "attach"
    assert a.json()["override"]["anchor_block_id"] == bid(2)
    assert env.st.enqueued[-1][1].docs == ["doc"] and env.st.enqueued[-1][1].to == "score2"
    d = await api.post(f"/api/figures/{FIG}/detach", json={"article_id": "doc"})
    assert d.json()["override"]["op"] == "detach" and d.json()["override"]["seq"] == 2
    b = await api.put(f"/api/figures/{FIG}/bbox", json={"bbox": [1, 2, 30, 40]})
    assert b.status_code == 202
    assert env.st.bboxes[FIG] == [1, 2, 30, 40]
    _, plan, _ = env.st.enqueued[-1]
    assert plan.force == ["figures"] and plan.docs == ["doc"] and plan.to == "score2"
    assert (
        await api.put(f"/api/figures/{FIG}/bbox", json={"bbox": [5, 5, 1, 1]})
    ).status_code == 422
    assert (
        await api.post("/api/figures/nope/attach", json={"article_id": "doc"})
    ).status_code == 422
    assert (await api.get("/api/figures/FIG-doc-p009-09/image")).status_code == 404
    kinds = [x.kind.value for x in env.st.actions]
    assert kinds == ["attach", "detach", "crop_bbox"]


async def test_a9_learning_round_trip(env: Env, api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/learning")).json()["enabled"] is False
    on = await api.put("/api/learning", json={"enabled": True, "use_global": False})
    assert on.json()["enabled"] is True and on.json()["use_global"] is False
    s1 = (await api.post("/api/learning/snapshots", json={"request_id": "s1"})).json()
    s2 = (await api.post("/api/learning/snapshots")).json()
    assert (s1["id"], s2["id"], s2["parent"]) == ("001", "002", "001")
    act2 = (await api.post("/api/learning/activate/002")).json()
    assert act2["active"] == "002" and act2["provenance"] == "snapshot:002"
    rb = (await api.post("/api/learning/rollback/001")).json()
    assert rb["active"] == "001"
    snaps = (await api.get("/api/learning/snapshots")).json()
    assert [s["active"] for s in snaps] == [True, False]
    rs = (await api.post("/api/learning/reset")).json()
    assert rs["active"] is None and rs["provenance"] == "baseline" and len(rs["snapshots"]) == 2
    assert (await api.post("/api/learning/items/ex-1/disable")).json()["id"] == "003"
    assert (await api.post("/api/learning/publish/001")).json()["id"] == "001"
    assert (await api.post("/api/learning/activate/099")).status_code == 404
    assert env.st.learning.enabled is True


async def test_doc_figures_lists_every_attachment(env: Env, api: httpx.AsyncClient) -> None:
    """G2: the re-attach picker lists the document's figures with all of their attachments."""
    from manuallabor.cleanup.types import ArticleAttachments, AttachFile, Attachment
    from manuallabor.contracts.block import Block
    from manuallabor.contracts.enums import AttachRule, BlockType
    from manuallabor.contracts.io import write_json
    from tests.api.fakes import FakeFigures

    paths = env.paths
    dp = paths.doc("doc")
    fid_block = Block(
        id=bid(9),
        doc_id="doc",
        page=1,
        bbox=[0, 0, 10, 10],
        type=BlockType.figure,
        reading_order=0,
        raw_text="",
        raw_source="pymupdf",
        figure_id=FIG,
    )
    dp.blocks.write_text("[" + fid_block.model_dump_json() + "]")
    paths.figure_dir("doc").mkdir(parents=True)
    write_json(paths.figure_file("doc", FIG, "json"), FakeFigures(env.st)._record())
    att = lambda a: ArticleAttachments(  # noqa: E731
        article_id=a,
        figures=[
            Attachment(
                figure_id=FIG, rule=AttachRule.proximity, confidence=0.9, anchor_block_id=None
            )
        ],
    )
    write_json(
        dp.attach,
        AttachFile(
            doc_id="doc",
            algo_version="2",
            fingerprint="0" * 64,
            article_split="per_topic",
            articles=[att("doc--a"), att("doc--b")],
            unattached=[],
            unresolved_refs=[],
            overrides_applied=0,
            overrides_stale=[],
        ),
    )
    r = await api.get("/api/docs/doc/figures")
    assert r.status_code == 200, r.text
    (item,) = r.json()
    assert item["figure_id"] == FIG and item["block_id"] == bid(9)
    assert [a["article_id"] for a in item["attachments"]] == ["doc--a", "doc--b"]
    assert item["image_url"] == f"/api/figures/{FIG}/image"
    assert (await api.get("/api/docs/nope/figures")).status_code == 404
