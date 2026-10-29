"""`labor status`, `labor decisions export`, `labor learning ...`, `labor run` errors."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from manuallabor.contracts.enums import BlockType
from manuallabor.project import ProjectPaths
from tests.state.helpers import Env

LABOR = [sys.executable, "-m", "manuallabor"]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(LABOR + list(args), capture_output=True, text=True, timeout=300)


def test_status_json_and_table(lp: ProjectPaths) -> None:
    r = run("status", str(lp.root), "--json")
    assert r.returncode == 0, r.stderr
    st = json.loads(r.stdout)
    assert st["project"] == "project-a" and [d["doc_id"] for d in st["docs"]] == [
        "clean",
        "scanned",
    ]
    assert all(n["state"] == "fresh" for d in st["docs"] for n in d["nodes"])
    assert all(d["learning"] == {"group": "baseline", "clean": "baseline"} for d in st["docs"])
    lp.doc("scanned").groups.unlink()
    table = run("status", str(lp.root), "-v").stdout
    assert "scanned" in table and "missing" in table and "STALE" in table
    assert "learning: group=baseline clean=baseline" in table
    assert run("status", str(lp.root / "nope")).returncode == 2


def test_status_reports_orphaned_decisions_and_unregistered_sources(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        victim = env.review.queue(None, None, "clean", 3, 0).items[0].block_id
        env.act("approve", victim)
    finally:
        env.close()
    real = lp.sources.resolve()  # `sources` is a shared symlink in test copies: unshare first
    lp.sources.unlink()
    shutil.copytree(real, lp.sources)
    (lp.sources / "extra.pdf").write_bytes(b"%PDF-1.4")
    st = json.loads(run("status", str(lp.root), "--json").stdout)
    assert st["unregistered_sources"] == ["extra.pdf"]
    assert [d["orphaned_decisions"] for d in st["docs"]] == [0, 0]
    # a re-parse changes the block's raw text: the decision is orphaned, not lost
    blocks = json.loads(lp.doc("clean").blocks.read_text())
    next(b for b in blocks if b["id"] == victim)["raw_text"] += " (re-parsed)"
    lp.doc("clean").blocks.write_text(json.dumps(blocks))
    st = json.loads(run("status", str(lp.root), "--json").stdout)
    assert [d["orphaned_decisions"] for d in st["docs"]] == [1, 0]


def test_decisions_export_is_canonical_ndjson(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        for item in env.review.queue(None, None, None, 3, 0).items:
            env.act("approve", item.block_id)
        n = env.store.count_actions()
    finally:
        env.close()
    out = run("decisions", "export", str(lp.root))
    assert out.returncode == 0
    lines = out.stdout.splitlines()
    assert len(lines) == n
    ids = [json.loads(x)["id"] for x in lines]
    assert ids == sorted(ids) and len(set(ids)) == n
    for line in lines:
        o = json.loads(line)
        assert line == json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    dest = lp.root / "out.ndjson"
    assert run("decisions", "export", str(lp.root), "--out", str(dest)).returncode == 0
    assert dest.read_text() == out.stdout


def test_learning_commands_round_trip(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        for item in env.review.queue(None, 1.0, "scanned", 40, 0).items:
            b = {x.id: x for x in env.blocks("scanned")}[item.block_id]
            if b.type == BlockType.paragraph and b.clean_text not in (None, b.raw_text):
                env.act("approve", b.id)
                break
    finally:
        env.close()
    assert "provenance=baseline" in run("learning", "list", str(lp.root)).stdout
    assert "snapshot 001 created" in run("learning", "snapshot", str(lp.root)).stdout
    assert "active=001" in run("learning", "activate", str(lp.root), "001").stdout
    assert "* 001" in run("learning", "list", str(lp.root)).stdout
    assert lp.learned_cleanup.is_file()
    assert "active=001" in run("learning", "rollback", str(lp.root), "001").stdout
    r = run("learning", "activate", str(lp.root), "009")
    assert r.returncode == 1 and "009" in r.stderr
    assert "learning reset" in run("learning", "reset", str(lp.root)).stdout
    assert not lp.learned_cleanup.exists()
    r = run("learning", "disable", str(lp.root), "ex-1")
    assert r.returncode == 1  # nothing active
    r = run("learning", "publish", str(lp.root), "001")
    assert r.returncode == 1 and "contribute_global" in r.stderr


def test_run_rejects_bad_arguments(lp: ProjectPaths) -> None:
    assert run("run", str(lp.root), "--to", "export", "--mock").returncode == 2
    assert run("run", str(lp.root), "--force", "nonsense", "--mock").returncode == 2
    assert run("run", str(lp.root / "nope")).returncode == 2


def test_stage_commands_keep_stages_json_true(lp: ProjectPaths) -> None:
    from manuallabor.jobs import graph

    before = graph.load_stages(lp, "clean").seq("score")
    r = run("score", str(lp.root), "--doc", "clean", "--force")
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    assert lines and all("node" not in o for o in lines)  # the stage's own output, untouched
    assert graph.load_stages(lp, "clean").seq("score") > before
    r = run("score", str(lp.root), "--doc", "nope")
    assert r.returncode == 1 and '"unknown document"' in r.stdout
    r = run("clean", str(lp.root), "--llm", "sometimes")
    assert r.returncode == 2
