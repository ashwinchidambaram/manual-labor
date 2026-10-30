"""Module 13 (design 13 section 2.8.3, owner decision D4): the queue card fields
`section_title`, `excerpt` and `weakest_word` on the real services over the mock-scored
two-document project (clean.pdf + scanned.pdf)."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from manuallabor.api.app import create_app
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.state.card import EXCERPT_MAX
from manuallabor.state.services import build_services

_OCR_MIN = re.compile(r"^min [0-9.]+ at (?P<word>.+); \d+ words$")


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


def _queue(c: TestClient) -> list[dict[str, Any]]:
    r = c.get("/api/verify/queue?limit=2000")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["items"])
    items: list[dict[str, Any]] = body["items"]
    return items


def test_queue_items_carry_the_card_fields(lp: ProjectPaths) -> None:
    services = build_services(lp, mode="mock", resume=False, clock=utc_now)
    try:
        c = TestClient(create_app(services, dev=True))
        items = _queue(c)
        assert items
        for it in items:
            assert {"section_title", "excerpt", "weakest_word"} <= it.keys()
            ex = it["excerpt"]
            assert isinstance(ex, str) and ex.strip(), it["block_id"]
            assert len(ex) <= EXCERPT_MAX, (it["block_id"], ex)
            assert "\n" not in ex and "\r" not in ex and "\t" not in ex and "  " not in ex
        titled = [it for it in items if it["section_title"]]
        assert titled, "no queue item has a section title"
        assert all("\n" not in it["section_title"] for it in titled)

        # weakest_word on a scanned block equals the word the OCR signal recorded
        checked = 0
        for it in items:
            if it["doc_id"] != "scanned" or it["type"] == "figure":
                continue
            d = c.get(f"/api/verify/blocks/{it['block_id']}").json()
            ocr_min = [w for w in d["why"] if w["kind"] == "signal" and w["name"] == "ocr_min"]
            if not ocr_min:
                continue
            m = _OCR_MIN.match(ocr_min[0]["detail"] or "")
            assert m is not None, ocr_min[0]["detail"]
            assert it["weakest_word"] == ast.literal_eval(m.group("word")), it["block_id"]
            checked += 1
            if checked == 5:
                break
        assert checked >= 1, "no scanned queue block with an ocr_min signal"

        # byte-identical on a re-read
        assert (
            c.get("/api/verify/queue?limit=2000").content
            == c.get("/api/verify/queue?limit=2000").content
        )
    finally:
        services.store.close()
