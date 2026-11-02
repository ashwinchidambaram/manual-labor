"""A project scored by an older SCORING_ALGO_VERSION reads as "not scored yet", never a 500
(design 03 section 2.10a, backend review 2 finding 1).

The verifier change bumped the version to "6". `load_scored_blocks` refuses a score file
of another version, and every read path that derived blocks from it used to raise
`ScoringError` into the API's JSON 500: Verify, Export, titles and the figure list stayed
broken until a rescore."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import scores_current
from manuallabor.scoring.types import SCORING_ALGO_VERSION
from manuallabor.state.models import FlagIn, ReviewActionIn
from tests.api.test_real_services import serving
from tests.state.helpers import Env

OLD = "5"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


def _downgrade(paths: ProjectPaths) -> None:
    for slug in paths.list_slugs():
        p = paths.doc(slug).scores
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["algo_version"] == SCORING_ALGO_VERSION != OLD
        data["algo_version"] = OLD
        p.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def test_old_score_files_read_as_not_scored_on_every_route(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:  # a decision and an open flag recorded before the upgrade
        page = env.review.queue(None, None, "clean", 5, 0)
        first, second = page.items[0].block_id, page.items[1].block_id
        env.act("approve", first)
        env.review.act(
            ReviewActionIn(
                kind="flag",
                block_id=second,
                flag=FlagIn(category="wrong_text", note="before the upgrade"),  # type: ignore[arg-type]
                request_id="t-flag",
            )
        )
        figs = sorted(p.stem for p in lp.figure_dir("clean").glob("FIG-*.json"))
        attach = json.loads(lp.doc("clean").attach.read_text(encoding="utf-8"))
        article = attach["articles"][0]["article_id"]
    finally:
        env.close()
    _downgrade(lp)
    assert not any(scores_current(lp, s) for s in lp.list_slugs())
    lp.doc("scanned").scores.unlink()  # and one never scored at all (review 2 finding 6)

    with serving(lp) as (c, _svc):
        gets = [
            "/api/agent/items",
            "/api/agent/proposals",
            f"/api/articles/{article}/figures",
            "/api/calibration",
            "/api/decisions/export",
            "/api/docs/clean/figures",
            "/api/docs/scanned/figures",
            "/api/docs/clean/pages/1/blocks",
            "/api/docs/clean/pages/1.png?dpi=36",
            "/api/export/status",
            "/api/flags",
            "/api/jobs",
            "/api/learning",
            "/api/learning/snapshots",
            "/api/project",
            "/api/scope/blocks",
            "/api/scope/groups",
            "/api/scope/selection",
            "/api/scope/summary",
            "/api/sources",
            "/api/status",
            "/api/verify/cursor",
            "/api/verify/queue",
            f"/api/verify/titles?ids={first}&ids={second}",
            f"/api/verify/blocks/{first}",
            *(f"/api/figures/{f}/image" for f in figs[:1]),
        ]
        codes = {u: c.get(u).status_code for u in gets}
        assert not {u: s for u, s in codes.items() if s >= 500}, codes

        q = c.get("/api/verify/queue").json()
        assert q["items"] == [] and q["total"] == 0
        states = {d["doc_id"]: d["state"] for d in q["docs"]}
        assert states == {s: "pending" for s in lp.list_slugs()}
        assert all(d["waiting_for"] for d in q["docs"]), q["docs"]  # names what must run
        assert c.get(f"/api/verify/titles?ids={first}").json() == []
        assert c.get("/api/docs/clean/figures").json() == []
        assert c.get("/api/docs/scanned/figures").json() == []
        assert c.get("/api/docs/clean/pages/1/blocks").json() == []
        assert codes[f"/api/verify/blocks/{first}"] == 404
        assert c.get("/api/scope/blocks").json() == []
        assert c.get("/api/export/status").json()["queued"] == 0
        # the stage graph already says what to do: score2 needs a run on every document
        st = c.get("/api/status").json()
        for d in st["docs"]:
            score2 = next(n for n in d["nodes"] if n["node"] == "score2")
            assert score2["state"] != "fresh", score2
        # nothing the reviewer recorded was lost
        assert [f["target_id"] for f in c.get("/api/flags").json()] == [second]


def test_scores_current_follows_the_file(lp: ProjectPaths) -> None:
    assert scores_current(lp, "clean")
    _downgrade(lp)
    assert not scores_current(lp, "clean")
    p = lp.doc("clean").scores
    p.write_text("{not json", encoding="utf-8")
    assert not scores_current(lp, "clean")
    p.unlink()
    assert not scores_current(lp, "clean")


def test_post_jobs_rescores_an_old_project_and_keeps_decisions(lp: ProjectPaths) -> None:
    """The Run button after an upgrade (`POST /api/jobs {to: score2}`, the reviewer's
    `api_upgrade_test.py`): `score` runs first, then group, clean and score2; no stage fails and
    the decisions, the flag and the selection survive (design 07 section 3.2 revision)."""
    from tests.jobs.test_upgrade_run import RESCORE, assert_upgraded, record_then_downgrade

    rec = record_then_downgrade(lp)
    slugs = lp.list_slugs()
    with serving(lp) as (c, svc):
        es = c.get("/api/export/status").json()
        # not "Ready to export": the gate cannot see these documents yet (review D3)
        assert es["not_ready"] == slugs and es["blockers"] == [], es
        assert es["counts"]["in_scope"] == 0
        svc.runner.start()
        try:
            r = c.post("/api/jobs", json={"to": "score2"})
            assert r.status_code == 202, r.text
            jid = r.json()["id"]
            deadline = time.monotonic() + 900
            job = r.json()
            while job["status"] not in ("done", "failed", "cancelled", "interrupted"):
                assert time.monotonic() < deadline, job
                time.sleep(0.2)
                job = c.get(f"/api/jobs/{jid}").json()
        finally:
            svc.runner.stop()
        assert job["status"] == "done", (job, c.get(f"/api/jobs/{jid}/log?limit=5000").json()[-6:])
        log = c.get(f"/api/jobs/{jid}/log?limit=5000").json()
        units = [(o["node"], o["doc"]) for o in log if o.get("event") == "unit_done"]
        assert units == [(n, s) for n in RESCORE for s in slugs], units
        assert not [o for o in log if o.get("status") in ("error", "failed", "blocked")]
        st = c.get("/api/status").json()
        assert all(n["state"] == "fresh" for d in st["docs"] for n in d["nodes"]), st
        q = c.get("/api/verify/queue").json()
        assert {d["doc_id"]: d["state"] for d in q["docs"]} == {s: "ready" for s in slugs}
        es = c.get("/api/export/status").json()
        assert es["not_ready"] == [] and es["counts"]["in_scope"] > 0, es
        assert [f["target_id"] for f in c.get("/api/flags").json()] == [rec.flagged]
    assert_upgraded(lp, rec)
