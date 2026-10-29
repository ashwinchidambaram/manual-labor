"""G1-G4, G8: node states, fingerprint equivalence, idempotent runs, planning, readiness."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from manuallabor.cleanup.pipeline import clean_fingerprints
from manuallabor.cleanup.types import AttachFile, CleanFile, DescribeFile
from manuallabor.contracts.group import GroupsFile
from manuallabor.contracts.io import read_json
from manuallabor.figures.pipeline import figures_fingerprint
from manuallabor.figures.types import FigureReport
from manuallabor.grouping.pipeline import group_fingerprint
from manuallabor.jobs import graph
from manuallabor.jobs.executor import make_plan, run_node
from manuallabor.parse.pipeline import parse_is_current
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import score_fingerprint
from manuallabor.scoring.types import ScoreFile
from manuallabor.state.learning import LearningService
from manuallabor.state.models import RegroupIn, ReviewActionIn, SelectionOp
from tests.state.helpers import Env

NODES = ["parse", "figures", "score", "group", "clean", "score2"]


def states(paths: ProjectPaths, slug: str) -> dict[str, str]:
    cfg = paths.load_config()
    return {s.node: s.state for s in graph.doc_node_states(paths, slug, cfg)}


def stale_set(paths: ProjectPaths, slug: str) -> set[str]:
    return {n for n, s in states(paths, slug).items() if s != "fresh"}


def hash_tree(paths: ProjectPaths) -> dict[str, str]:
    out = {}
    for root in (paths.docs, paths.figures_root):
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.name != "stages.json":
                out[str(f.relative_to(paths.root))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def test_g1_after_a_full_run_everything_is_fresh(lp: ProjectPaths) -> None:
    for slug in lp.list_slugs():
        assert states(lp, slug) == {n: "fresh" for n in ["ingest", *NODES]}


def test_g1_figures_force_marks_every_downstream_node_stale(lp: ProjectPaths) -> None:
    assert run_node(lp, "figures", only="clean", force=True, emit=lambda _o: None) == []
    st = states(lp, "clean")
    assert st["figures"] == "fresh"
    assert {n for n in NODES if st[n] != "fresh"} == {"score", "group", "clean", "score2"}
    assert stale_set(lp, "scanned") == set()  # only the forced document


def test_g1_selection_change_marks_clean_and_score2(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        victim = next(b for b in env.data.selection().block_ids if b.startswith("b-clean-"))
        env.scope.apply(SelectionOp(op="deselect", block_ids=[victim], request_id="s"))
    finally:
        env.close()
    assert stale_set(lp, "clean") == {"clean", "score2"}
    assert stale_set(lp, "scanned") == set()  # fingerprints only see their own document's blocks


def test_g1_group_override_marks_group_to_score2(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        gf = env.data.groups("clean")
        assert gf is not None
        t = next(t for t in gf.topics if not t.is_unassigned)
        env.scope.regroup(
            RegroupIn(doc_id="clean", kind="rename", topic_slug=t.slug, title="New", request_id="g")
        )
    finally:
        env.close()
    assert stale_set(lp, "clean") == {"group", "clean", "score2"}
    assert stale_set(lp, "scanned") == set()


def test_g1_project_threshold_marks_score(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        env.scope.set_project_threshold(0.9, "cli", "t")
    finally:
        env.close()
    assert lp.load_config().threshold == 0.9
    st = states(lp, "clean")
    assert st["score"] == "stale" and st["parse"] == st["figures"] == "fresh"
    assert st["score2"] == "stale"


def test_g1_learning_toggle_marks_group_and_clean(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        svc = LearningService(lp, env.store)
        snap = svc.snapshot("a")
        svc.activate(snap.id, "b")
        assert stale_set(lp, "clean") == set()  # learning is off: baseline either way
        svc.set_flags(True, None, None, "c")
    finally:
        env.close()
    assert stale_set(lp, "clean") == {"group", "clean", "score2"}


def test_g1_deleted_output_is_missing(lp: ProjectPaths) -> None:
    lp.doc("clean").groups.unlink()
    st = states(lp, "clean")
    assert st["group"] == "missing"
    assert st["clean"] == "stale" and st["score2"] == "stale"


def test_g2_fingerprints_equal_the_recorded_ones(lp: ProjectPaths) -> None:
    cfg = lp.load_config()
    for slug in lp.list_slugs():
        dp = lp.doc(slug)
        assert read_json(dp.figure_report, FigureReport).fingerprint == figures_fingerprint(
            lp, slug
        )
        assert read_json(dp.scores, ScoreFile).fingerprint == score_fingerprint(lp, slug, cfg)
        assert read_json(dp.groups, GroupsFile).fingerprint == group_fingerprint(lp, slug, cfg)
        assert (
            read_json(dp.clean, CleanFile).fingerprint,
            read_json(dp.attach, AttachFile).fingerprint,
            read_json(dp.describe, DescribeFile).fingerprint,
        ) == clean_fingerprints(lp, slug, cfg)
        assert parse_is_current(lp, slug, cfg)
    cfg2 = cfg.model_copy(update={"ocr_dpi": 400})
    assert not parse_is_current(lp, "clean", cfg2)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "manuallabor", *args], capture_output=True, text=True, timeout=300
    )


def test_g3_second_run_does_nothing(lp: ProjectPaths) -> None:
    before = hash_tree(lp)
    r = run_cli("run", str(lp.root), "--mock")
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    assert all(o.get("status") == "skip" for o in lines if "stage" in o)
    assert hash_tree(lp) == before
    # forcing the clean node re-runs clean, attach, describe and then score2, same bytes
    r = run_cli("run", str(lp.root), "--mock", "--force", "clean", "--to", "score2")
    assert r.returncode == 0, r.stderr
    assert hash_tree(lp) == before


def test_g4_plan_is_node_major_and_scoped(lp: ProjectPaths) -> None:
    cfg = lp.load_config()
    assert make_plan(lp, cfg).units == []
    for slug in ("clean", "scanned"):
        lp.doc(slug).groups.unlink()
    plan = make_plan(lp, cfg)
    assert plan.units == [
        ("group", "clean"),
        ("group", "scanned"),
        ("clean", "clean"),
        ("clean", "scanned"),
        ("score2", "clean"),
        ("score2", "scanned"),
    ]
    assert make_plan(lp, cfg, to="group").units == [("group", "clean"), ("group", "scanned")]
    assert make_plan(lp, cfg, docs=["scanned"]).units == [
        ("group", "scanned"),
        ("clean", "scanned"),
        ("score2", "scanned"),
    ]
    with pytest.raises(ValueError):
        make_plan(lp, cfg, to="export")
    with pytest.raises(ValueError):
        make_plan(lp, cfg, docs=["nope"])


def test_g4_a_stale_parse_schedules_that_documents_downstream_only(lp: ProjectPaths) -> None:
    cfg = lp.load_config()
    lp.doc("scanned").state.unlink()
    plan = make_plan(lp, cfg)
    assert plan.units == [(n, "scanned") for n in NODES]


def test_g4_reparse_with_decisions_is_refused(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        page = env.review.queue(None, None, "scanned", 5, 0)
        env.review.act(
            ReviewActionIn(kind="approve", block_id=page.items[0].block_id, request_id="x")
        )
    finally:
        env.close()
    cfg = lp.load_config()
    lp.doc("scanned").state.unlink()
    plan = make_plan(lp, cfg)
    assert plan.units == [] and plan.refused and plan.refused[0][0] == "scanned"
    plan = make_plan(lp, cfg, allow_reparse=True)
    assert plan.units[0] == ("parse", "scanned") and not plan.refused


def test_g8_readiness_lists_only_scored_documents(labor_template: Path, tmp_path: Path) -> None:
    from manuallabor.jobs.inline import run_inline
    from manuallabor.state.models import RunPlanIn
    from manuallabor.state.store import Store
    from tests.conftest import labor_copy

    paths = ProjectPaths(labor_copy(labor_template, tmp_path / "proj"))
    store = Store.open(paths)
    for docs, to in ((["clean"], "score2"), (["scanned"], "group")):
        res = run_inline(
            paths, RunPlanIn(to=to, docs=docs), mode="mock", emit=lambda _o: None, store=store
        )
        assert res.ok
    store.close()
    env = Env(paths)
    try:
        page = env.review.queue(None, None, None, 5000, 0)
        assert page.items and {i.doc_id for i in page.items} == {"clean"}
        by = {d.doc_id: d for d in page.docs}
        assert by["clean"].state == "ready" and by["clean"].stale is False
        assert by["scanned"].state == "pending" and by["scanned"].waiting_for == "clean"
    finally:
        env.close()


def test_stages_json_has_no_timestamps(lp: ProjectPaths) -> None:
    st = json.loads(lp.doc("clean").stages.read_text())
    assert set(st) == {"counter", "nodes"}
    for rec in st["nodes"].values():
        assert set(rec) == {"seq", "status", "fingerprint", "error"}
    assert graph.load_stages(lp, "clean").seq("score2") > graph.load_stages(lp, "clean").seq(
        "clean"
    )
