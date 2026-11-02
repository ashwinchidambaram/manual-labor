"""`labor run` after an upgrade re-scores a project whose score files carry an older
`SCORING_ALGO_VERSION` (design 03 section 2.10a, design 07 section 3.2 revision 2026-11-02).

Before the fix the stage graph called `score` fresh whenever clean.json existed, so the plan
started at `group`, whose fingerprint carries the algo version; `group` then refused the old
scores ("scores.json missing or from another algo version"), `stages.json` recorded
`group: failed` on every run and the export stayed locked. README "Upgrading" promises that
`labor run <project>` is enough."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from manuallabor.jobs import graph
from manuallabor.jobs.executor import make_plan
from manuallabor.jobs.render import render_status
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import scores_current
from manuallabor.scoring.types import SCORING_ALGO_VERSION
from manuallabor.state.models import FlagIn, ReviewActionIn, SelectionOp
from tests.state.helpers import Env

OLD = "5"
DOC_NODES = ["parse", "figures", "score", "group", "clean", "score2"]
RESCORE = ["score", "group", "clean", "score2"]
LABOR = [sys.executable, "-m", "manuallabor"]


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


@dataclass(frozen=True)
class Recorded:
    """What the reviewer recorded before the upgrade."""

    approved: str
    flagged: str
    deselected: str
    decisions: list[tuple[str, str, str]]
    flags: list[tuple[str, str, str]]
    selection: list[str]


def _snapshot(env: Env) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]], list[str]]:
    decisions = [
        (d.decision.block_id, d.decision.action.value, d.raw_sha256) for d in env.store.decisions()
    ]
    flags = [(f.id, f.target_id, f.status.value) for f in env.store.flags()]
    return decisions, flags, sorted(env.data.selection().block_ids)


def record_then_downgrade(lp: ProjectPaths) -> Recorded:
    """A decision, an open flag and a narrowed selection, then every score file rewritten to
    algo version "5" (a project made before the 2026-10-30 version)."""
    env = Env(lp)
    try:
        page = env.review.queue(None, None, "clean", 5, 0)
        approved, flagged = page.items[0].block_id, page.items[1].block_id
        env.act("approve", approved)
        env.review.act(
            ReviewActionIn(
                kind="flag",
                block_id=flagged,
                flag=FlagIn(category="wrong_text", note="before the upgrade"),  # type: ignore[arg-type]
                request_id="t-flag",
            )
        )
        sel = sorted(env.data.selection().block_ids)
        deselected = next(b for b in sel if b not in (approved, flagged) and "-scanned-" in b)
        env.scope.apply(SelectionOp(op="deselect", block_ids=[deselected], request_id="t-sel"))
        decisions, flags, selection = _snapshot(env)
    finally:
        env.close()
    assert deselected not in selection and len(decisions) == 2 and len(flags) == 1
    downgrade(lp)
    return Recorded(approved, flagged, deselected, decisions, flags, selection)


def downgrade(paths: ProjectPaths) -> None:
    """Score files of algo "5", and groups.json fingerprints made under it (`group`'s
    fingerprint carries `SCORING_ALGO_VERSION`, design 04 step 2), as in build/human-test."""
    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        data = json.loads(dp.scores.read_text(encoding="utf-8"))
        assert data["algo_version"] == SCORING_ALGO_VERSION != OLD
        data["algo_version"] = OLD
        dp.scores.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        groups = json.loads(dp.groups.read_text(encoding="utf-8"))
        groups["fingerprint"] = "5" * 64  # any value but the current one
        dp.groups.write_text(json.dumps(groups, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    assert not any(scores_current(paths, s) for s in paths.list_slugs())


def assert_upgraded(lp: ProjectPaths, rec: Recorded) -> None:
    """Every node fresh and none failed, the scores current, and nothing the reviewer recorded
    lost: the same decisions (not orphaned), the same open flag, the same selection."""
    cfg = lp.load_config()
    for slug in lp.list_slugs():
        st = {s.node: (s.state, s.reason) for s in graph.doc_node_states(lp, slug, cfg)}
        assert all(v[0] == "fresh" for v in st.values()), (slug, st)
        recs = graph.load_stages(lp, slug).nodes
        assert not [n for n, r in recs.items() if r.status == "failed"], (slug, recs)
        assert scores_current(lp, slug)
    env = Env(lp)
    try:
        decisions, flags, selection = _snapshot(env)
        assert decisions == rec.decisions
        assert flags == rec.flags
        assert selection == rec.selection and rec.deselected not in selection
        by_id = {b.id: b for b in env.blocks("clean")}
        assert by_id[rec.approved].status.value == "approved"
        st = graph.project_status(lp, None)
        assert [d.orphaned_decisions for d in st.docs] == [0, 0]
    finally:
        env.close()


def test_old_scores_make_score_stale_and_say_why(lp: ProjectPaths) -> None:
    downgrade(lp)
    cfg = lp.load_config()
    for slug in lp.list_slugs():
        st = {s.node: s for s in graph.doc_node_states(lp, slug, cfg)}
        assert [n for n in DOC_NODES if st[n].state != "fresh"] == RESCORE, st
        assert st["score"].state == "stale"  # "Needs a run" on the Scope chip, not "Not run yet"
        assert st["score"].reason is not None and OLD in st["score"].reason
        assert SCORING_ALGO_VERSION in st["score"].reason
        assert st["score2"].state == "stale" and OLD in (st["score2"].reason or "")
    table = render_status(graph.project_status(lp, None), verbose=True)
    assert "score: stale (scored by scoring version 5" in table, table


def test_unreadable_score_file_is_stale_not_fresh(lp: ProjectPaths) -> None:
    lp.doc("clean").scores.write_text("{not json", encoding="utf-8")
    st = {s.node: s for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert st["score"].state == "stale" and st["score"].reason == "scores.json unreadable"
    assert st["score2"].state == "stale"


def test_make_plan_starts_at_score_for_old_scores(lp: ProjectPaths) -> None:
    downgrade(lp)
    plan = make_plan(lp, lp.load_config(), to="score2")
    slugs = lp.list_slugs()
    assert plan.units == [(n, s) for n in RESCORE for s in slugs]
    # `--to score` (and the Scope screen's Re-run, `to: group`) start there too
    assert make_plan(lp, lp.load_config(), to="score").units == [("score", s) for s in slugs]


def test_labor_run_mock_rescores_an_old_project_and_keeps_decisions(lp: ProjectPaths) -> None:
    rec = record_then_downgrade(lp)
    r = subprocess.run(
        [*LABOR, "run", str(lp.root), "--mock"], capture_output=True, text=True, timeout=900
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    done = [(o["node"], o["doc"]) for o in lines if o.get("event") == "unit_done"]
    assert done == [(n, s) for n in RESCORE for s in lp.list_slugs()], done
    assert all(o["status"] == "done" for o in lines if o.get("event") == "unit_done")
    assert not [o for o in lines if o.get("status") in ("error", "blocked")]
    assert_upgraded(lp, rec)
    status = subprocess.run(
        [*LABOR, "status", str(lp.root)], capture_output=True, text=True, timeout=120
    )
    assert "STALE" not in status.stdout and "FAILED" not in status.stdout, status.stdout


# -- fresh review of the upgrade fix (integration 2026-11-02) ----------------------------------


def test_clean_on_an_old_project_says_it_waits_for_score(lp: ProjectPaths) -> None:
    """Review finding 5: `clean`'s reason was the raw `CleanupError` text pointing at `labor
    score`; an upstream node that is not fresh is the reason."""
    downgrade(lp)
    st = {s.node: s for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert st["clean"].state == "stale"
    assert st["clean"].reason == "upstream score is stale", st["clean"]
    table = render_status(graph.project_status(lp, None), verbose=True)
    assert "CleanupError" not in table and "Error:" not in table, table


def test_score_is_stale_when_its_file_does_not_cover_every_block(lp: ProjectPaths) -> None:
    """Review finding 2: a current-version scores.json that misses a block of blocks.json (a
    re-parse that outran it) made `score` fresh while clean.json existed, so the plan started
    later and every stage that loads the machine view raised "has no score"."""
    p = lp.doc("clean").scores
    data = json.loads(p.read_text(encoding="utf-8"))
    dropped = data["blocks"].pop()["block_id"]
    p.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    assert scores_current(lp, "clean")
    st = {s.node: s for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert st["score"].state == "stale", st["score"]
    assert st["score"].reason == "scores.json has no score for 1 block", st["score"]
    assert dropped
    units = make_plan(lp, lp.load_config(), to="score2").units
    assert units[0] == ("score", "clean"), units
    assert [u for u in units if u[1] == "scanned"] == []
    # the run brings it back: `score` does not take its skip path for a file that misses a block
    r = subprocess.run(
        [*LABOR, "run", str(lp.root), "--mock"], capture_output=True, text=True, timeout=900
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    st = {s.node: s for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert all(s.state == "fresh" for s in st.values()), st
    data = json.loads(p.read_text(encoding="utf-8"))
    assert dropped in {b["block_id"] for b in data["blocks"]}


def test_a_failing_check_over_fresh_upstream_keeps_its_error(lp: ProjectPaths) -> None:
    """When every upstream node is fresh, the node's own error is the reason."""
    lp.doc("clean").groups.write_text("{not json", encoding="utf-8")
    st = {s.node: s for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert st["score"].state == "fresh", st["score"]
    assert st["group"].state == "stale" and "GroupsFile" in (st["group"].reason or "")
    assert st["clean"].reason == "upstream group is stale", st["clean"]


def test_re_run_to_group_starts_at_score_on_an_old_project(lp: ProjectPaths) -> None:
    """The Scope screen's Re-run posts `to: group`."""
    downgrade(lp)
    slugs = lp.list_slugs()
    units = make_plan(lp, lp.load_config(), to="group").units
    assert units == [(n, s) for n in ("score", "group") for s in slugs], units


def test_a_project_that_already_recorded_group_failed_plans_score_first(lp: ProjectPaths) -> None:
    """The real upgrade state: earlier runs recorded `group: failed` in stages.json."""
    downgrade(lp)
    for slug in lp.list_slugs():
        st = graph.load_stages(lp, slug)
        st.record("group", "failed", None, "ScoringError: scores.json missing or from another")
        graph.save_stages(lp, slug, st)
    slugs = lp.list_slugs()
    states = {s.node: s.state for s in graph.doc_node_states(lp, slugs[0], lp.load_config())}
    assert states["score"] == "stale" and states["group"] == "failed", states
    assert make_plan(lp, lp.load_config(), to="score2").units == [
        (n, s) for n in RESCORE for s in slugs
    ]


def test_no_score_file_beside_clean_json_is_missing(lp: ProjectPaths) -> None:
    lp.doc("clean").scores.unlink()
    st = {s.node: s.state for s in graph.doc_node_states(lp, "clean", lp.load_config())}
    assert st["score"] == "missing" and st["score2"] == "missing", st
    assert make_plan(lp, lp.load_config(), to="score2").units[0] == ("score", "clean")


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",  # valid JSON, not an object
        "{}",  # no algo_version
        '{"algo_version": 5}',  # not a string
        json.dumps({"algo_version": SCORING_ALGO_VERSION}),  # this version, but not a ScoreFile
    ],
)
def test_an_unusable_score_file_is_unreadable(tmp_path: Path, text: str) -> None:
    p = tmp_path / "scores.json"
    p.write_text(text, encoding="utf-8")
    assert graph._old_scores_reason(p) == "scores.json unreadable"
    p.write_text(json.dumps({"algo_version": OLD}), encoding="utf-8")
    assert graph._old_scores_reason(p) == (
        f"scored by scoring version {OLD}; this version is {SCORING_ALGO_VERSION}"
    )
