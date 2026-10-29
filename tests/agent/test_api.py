"""Design 10 tests 29-30: the agent and calibration routes over real services, and the
guarantee that no route calls a model."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from manuallabor.api.app import create_app
from manuallabor.api.deps import Hooks
from manuallabor.calibration.apply import CalibrationService
from manuallabor.contracts.proposal import Proposal
from manuallabor.providers.base import BaseProvider
from manuallabor.state.interfaces import AppServices
from manuallabor.state.learning import LearningService
from tests.agent.conftest import AEnv


@pytest.fixture
def client(aenv: AEnv) -> Iterator[TestClient]:
    svc = AppServices(
        paths=aenv.paths,
        store=aenv.store,
        review=aenv.review,
        scope=aenv.scope,
        figures=aenv.figures,
        learning=LearningService(aenv.paths, aenv.store),
        runner=aenv.runner,
        mock=True,
        agent=aenv.agent,
        calibration=CalibrationService(aenv.paths, aenv.store, aenv.data, aenv.runner),
    )
    with TestClient(create_app(svc, hooks=Hooks())) as c:
        yield c


def test_29_no_stub_left(client: TestClient) -> None:
    ops = client.get("/openapi.json").json()["paths"]
    mine = {p: o for p, o in ops.items() if p.startswith(("/api/agent", "/api/calibration"))}
    assert len(mine) == 9
    for p, o in mine.items():
        for method in o.values():
            assert "501" not in method["responses"], p


def test_29_routes(client: TestClient, aenv: AEnv) -> None:
    flags = aenv.seed()
    items = client.get("/api/agent/items").json()
    assert [i["flag"]["id"] for i in items] == flags and {i["round"] for i in items} == {1}
    r = client.post("/api/agent/run", json={"request_id": "run-1"})
    assert r.status_code == 202 and r.json()["kind"] == "agent"
    assert (
        client.post("/api/agent/run", json={"request_id": "run-1"}).json()["id"] == r.json()["id"]
    )
    assert r.json()["plan"]["items"] and len(r.json()["plan"]["items"]) == 5
    aenv.run_agent()  # the worker's part
    props = [Proposal.model_validate(p) for p in client.get("/api/agent/proposals").json()]
    assert len(props) == 5
    assert len(client.get("/api/agent/proposals?status=pending").json()) == 5
    assert client.get("/api/agent/proposals?status=rejected").json() == []
    assert len(client.get(f"/api/agent/proposals?flag_id={flags[0]}").json()) == 1
    assert len(client.get("/api/agent/proposals?doc=figures").json()) == 2
    assert client.get("/api/agent/proposals?flag_id=bad").status_code == 422
    assert client.post("/api/agent/proposals/prop-999999/accept", json={}).status_code == 404
    failing = next(p for p in props if not p.all_checks_passed)
    r = client.post(f"/api/agent/proposals/{failing.id}/accept", json={"request_id": "a1"})
    assert r.status_code == 409 and r.json()["code"] == "checks_failed"
    attach = next(p for p in props if p.kind.value == "attach")
    assert (
        client.post(f"/api/agent/proposals/{attach.id}/edit", json={"text": "x"}).status_code == 422
    )
    r = client.post(f"/api/agent/proposals/{attach.id}/accept", json={"request_id": "a2"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    r = client.post(f"/api/agent/proposals/{attach.id}/accept", json={"request_id": "a3"})
    assert r.status_code == 409 and r.json()["code"] == "not_pending"
    text = next(p for p in props if p.kind.value == "text")
    r = client.post(
        f"/api/agent/proposals/{text.id}/reject", json={"reason": "no", "request_id": "r1"}
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = client.post("/api/agent/accept-all-passing", json={"request_id": "all-1"})
    assert r.status_code == 200 and isinstance(r.json(), list)
    rep = client.get("/api/calibration").json()
    assert (
        rep["scope"] == "project" and len(rep["buckets"]) == 20 and rep["target_edit_rate"] == 0.02
    )
    assert rep["suggestion_reason"] == "insufficient_data" and rep["suggested_threshold"] is None
    assert client.get("/api/calibration?scope=global").json()["scope"] == "project"
    ap = client.post("/api/calibration/apply", json={"threshold": 0.8, "request_id": "c1"})
    assert ap.status_code == 200
    body = ap.json()
    assert body["threshold"] == 0.8 and body["scope"] == "next_docs" and body["job"] is None
    assert body["pinned"] == ["clean", "figures"]
    assert client.post("/api/calibration/apply", json={"threshold": 2}).status_code == 422


def test_30_no_route_calls_a_model(
    client: TestClient, aenv: AEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    aenv.seed()
    aenv.run_agent()

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a model was called from an API route")

    for name in ("chat", "vision", "embed", "_chat_raw", "_vision_raw", "_embed_raw"):
        monkeypatch.setattr(BaseProvider, name, boom, raising=False)
    from manuallabor.providers.mock import MockProvider

    for name in ("chat", "vision", "embed", "_chat_raw", "_vision_raw", "_embed_raw"):
        monkeypatch.setattr(MockProvider, name, boom, raising=False)
    assert client.get("/api/agent/items").status_code == 200
    props = client.get("/api/agent/proposals").json()
    assert len(props) == 5
    ok = next(p for p in props if p["kind"] == "attach")
    assert (
        client.post(
            f"/api/agent/proposals/{ok['id']}/accept", json={"request_id": "x1"}
        ).status_code
        == 200
    )
    other = next(p for p in props if p["kind"] == "regroup")
    assert (
        client.post(
            f"/api/agent/proposals/{other['id']}/reject", json={"request_id": "x2"}
        ).status_code
        == 200
    )
    assert client.post("/api/agent/accept-all-passing", json={}).status_code == 200
    assert client.get("/api/calibration").status_code == 200
    assert client.post("/api/calibration/apply", json={"threshold": 0.7}).status_code == 200
