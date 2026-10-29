"""G5, G7: the module 7 gate. Kill mid-run, restart, continue: the result is byte-identical to
an uninterrupted run (R1-R6)."""

from __future__ import annotations

import hashlib
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.io import read_json, write_json
from manuallabor.project import ProjectPaths
from manuallabor.state.models import ReviewActionIn
from manuallabor.state.store import Store
from tests.conftest import labor_copy

LABOR = [sys.executable, "-m", "manuallabor"]


def hash_map(paths: ProjectPaths) -> dict[str, str]:
    out: dict[str, str] = {}
    roots = [paths.docs, paths.figures_root, paths.learning]
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            rel = f.relative_to(paths.root)
            if not f.is_file() or f.name == "stages.json" or ".partial" in rel.parts:
                continue
            if "pages" in rel.parts or "pages_view" in rel.parts:
                continue
            out[str(rel)] = hashlib.sha256(f.read_bytes()).hexdigest()
    if paths.selection.is_file():
        out["selection.json"] = hashlib.sha256(paths.selection.read_bytes()).hexdigest()
    return out


def cache_keys(paths: ProjectPaths) -> set[str]:
    d = paths.root / ".llm_cache"
    return {p.name for p in d.glob("*.json")} if d.is_dir() else set()


def stray_tmp(paths: ProjectPaths) -> list[Path]:
    return [
        p
        for root in (paths.docs, paths.figures_root, paths.learning)
        if root.is_dir()
        for p in root.rglob("*.tmp")
    ]


def run_to_completion(
    root: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, **(env or {})}
    return subprocess.run(
        [*LABOR, "run", str(root), "--mock"], capture_output=True, text=True, env=e, timeout=600
    )


def all_fresh(root: Path) -> bool:
    r = subprocess.run(
        [*LABOR, "status", str(root), "--json"], capture_output=True, text=True, timeout=120
    )
    st = json.loads(r.stdout)
    return all(n["state"] == "fresh" for d in st["docs"] for n in d["nodes"])


def kill_when(
    root: Path, node: str, seed: int, env: dict[str, str] | None = None
) -> tuple[int, list[dict[str, Any]]]:
    """Start `labor run`, SIGKILL its process group `uniform(0, 0.1)` s after the first stage
    line of `node` (a stage reports a document when it is done, so the window has to be short
    to land while the next document's unit runs). Returns the pgid and every progress line
    printed before the kill (stage lines and `unit_done` events). Skips when the run finished
    first."""
    e = {**os.environ, **(env or {})}
    p = subprocess.Popen(
        [*LABOR, "run", str(root), "--mock"],
        stdout=subprocess.PIPE,
        text=True,
        env=e,
        start_new_session=True,
    )
    assert p.stdout is not None
    pgid = os.getpgid(p.pid)
    seen: list[str] = []
    for line in p.stdout:
        seen.append(line)
        if line.startswith("{") and json.loads(line).get("node") == node:
            break
    time.sleep(random.Random(seed).uniform(0, 0.1))
    os.killpg(pgid, signal.SIGKILL)
    seen.extend(p.stdout.read().splitlines())  # what was flushed before the kill
    p.wait()
    if p.returncode != -signal.SIGKILL:
        pytest.skip(f"the run finished (exit {p.returncode}) before the kill landed")
    return pgid, [json.loads(x) for x in seen if x.startswith("{") and x.rstrip().endswith("}")]


def assert_killed_during(root: Path, node: str, progress: list[dict[str, Any]]) -> None:
    """The kill landed while `node` was running: it had started (a stage line of it) and not
    every document's `node` unit was done. A kill that landed after `node` finished is skipped
    (the window was missed, nothing about resuming `node` was tested)."""
    assert any(o.get("node") == node and "stage" in o for o in progress), progress[-5:]
    done = {o["doc"] for o in progress if o.get("event") == "unit_done" and o.get("node") == node}
    slugs = set(ProjectPaths(root).list_slugs())
    if done >= slugs:
        pytest.skip(f"{node} had finished for every document before the kill landed")
    assert done < slugs


def assert_no_group_members(pgid: int) -> None:
    r = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True)
    assert r.stdout.strip() == "", f"orphans left in the process group: {r.stdout}"


@pytest.fixture(scope="module")
def reference(labor_scored: Path) -> ProjectPaths:
    return ProjectPaths(labor_scored)


def fresh_copy(labor_template: Path, tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(labor_copy(labor_template, tmp_path / "proj"))


def assert_resumed_equals(resumed: ProjectPaths, ref: ProjectPaths) -> None:
    assert stray_tmp(resumed) == []
    assert hash_map(resumed) == hash_map(ref)
    assert cache_keys(ref) <= cache_keys(resumed)
    assert all_fresh(resumed.root)


@pytest.mark.parametrize(("node", "seed"), [("score", 11), ("clean", 23)])
def test_r1_random_sigkill_then_resume(
    labor_template: Path, reference: ProjectPaths, tmp_path: Path, node: str, seed: int
) -> None:
    p = fresh_copy(labor_template, tmp_path)
    pgid, progress = kill_when(p.root, node, seed)
    assert_killed_during(p.root, node, progress)
    assert_no_group_members(pgid)
    r = run_to_completion(p.root)
    assert r.returncode == 0, r.stderr
    assert_resumed_equals(p, reference)


@pytest.mark.parametrize(
    "fault",
    [
        "node.after:score:clean",
        "node.after:clean:scanned",
        "score.after_history",
        "score.after_scores",
    ],
)
def test_r2_deterministic_fault_points(
    labor_template: Path, reference: ProjectPaths, tmp_path: Path, fault: str
) -> None:
    p = fresh_copy(labor_template, tmp_path)
    r = run_to_completion(p.root, {"MANUALLABOR_FAULT": fault})
    assert r.returncode == -signal.SIGKILL, (fault, r.returncode, r.stderr[-500:])
    r = run_to_completion(p.root)
    assert r.returncode == 0, r.stderr
    assert_resumed_equals(p, reference)
    assert (p.doc("clean").score_history).read_bytes() == reference.doc(
        "clean"
    ).score_history.read_bytes()


def test_r2_kill_during_llm_calls_of_clean(labor_template: Path, tmp_path: Path) -> None:
    """cleanup.llm=always makes the mock model run; kill after the 3rd call inside `clean`."""
    base = fresh_copy(labor_template, tmp_path / "ref")
    cfg = base.load_config()
    always = cfg.model_copy(update={"cleanup": cfg.cleanup.model_copy(update={"llm": "always"})})
    write_json(base.config, always)
    assert run_to_completion(base.root).returncode == 0
    p = fresh_copy(labor_template, tmp_path / "killed")
    write_json(p.config, always)
    r = run_to_completion(p.root, {"MANUALLABOR_FAULT": "llm.after_calls:clean:3"})
    assert r.returncode == -signal.SIGKILL, (r.returncode, r.stderr[-500:])
    assert len(cache_keys(p)) >= 3  # every completed call was cached before the kill
    r = run_to_completion(p.root)
    assert r.returncode == 0, r.stderr
    assert_resumed_equals(p, base)


def run_child(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.jobs.children", *args],
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_r3_kill_inside_the_decision_transaction(lp: ProjectPaths) -> None:
    r = run_child(lp.root, "review", str(lp.root), "5", "action.after_insert")
    assert r.returncode == -signal.SIGKILL, r.stderr[-800:]
    outs = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    assert len(outs) == 5
    store = Store.open(lp)
    try:
        assert store.integrity_ok()
        assert store.max_action_id() == outs[-1]["action_id"]
        assert len(store.decisions()) == 5
        cur = store.get_cursor()
        assert cur is not None and cur.model_dump(mode="json") == outs[-1]["cursor"]
        # the 6th action can be applied again after the restart
        from manuallabor.state.data import ProjectData
        from manuallabor.state.review import ReviewService

        rv = ReviewService(lp, store, ProjectData(lp, store))
        nxt = rv.queue(None, None, None, 1, 0).items[0].block_id
        out = rv.act(ReviewActionIn(kind="approve", block_id=nxt, request_id="after-restart"))
        assert out.action_id == outs[-1]["action_id"] + 1
    finally:
        store.close()


def test_r4_kill_between_commit_and_projection(lp: ProjectPaths) -> None:
    r = run_child(lp.root, "selection", str(lp.root), "action.after_commit")
    assert r.returncode == -signal.SIGKILL, r.stderr[-800:]
    assert "first" in r.stdout and "unreachable" not in r.stdout
    stale = lp.selection.read_bytes()  # holds the first op, not the second
    store = Store.open(lp, reconcile=False)
    try:
        body = store.get_selection_json()
        assert body is not None
        from manuallabor.contracts.io import dump_json
        from manuallabor.contracts.selection import Selection

        committed = dump_json(Selection.model_validate_json(body))
        assert committed.encode() != stale  # the DB is ahead of the file
    finally:
        store.close()
    Store.open(lp).close()  # reopening heals the projection
    assert lp.selection.read_bytes() == committed.encode()
    _ = read_json
