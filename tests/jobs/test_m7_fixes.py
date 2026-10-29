"""Module 7 review fixes: the re-parse guard on `labor parse`, the actual stage error in the job
row, `labor learning list` read-only while the project is held."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys

from manuallabor.contracts.enums import BlockType
from manuallabor.jobs.inline import run_inline
from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.state.lock import ProjectLock
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store
from tests.jobs.test_runner import wait_for
from tests.state.helpers import Env

LABOR = [sys.executable, "-m", "manuallabor"]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(LABOR + list(args), capture_output=True, text=True, timeout=600)


def _decide(lp: ProjectPaths, slug: str, n: int) -> None:
    env = Env(lp)
    try:
        items = [i for i in env.review.queue(None, None, slug, 50, 0).items]
        done = 0
        for item in items:
            if item.type != BlockType.figure:
                env.act("skip" if done else "approve", item.block_id)
                done += 1
            if done == n:
                break
    finally:
        env.close()


def test_labor_parse_force_is_refused_on_a_doc_with_decisions(lp: ProjectPaths) -> None:
    _decide(lp, "scanned", 2)
    blocks = lp.doc("scanned").blocks
    before = hashlib.sha256(blocks.read_bytes()).hexdigest()
    r = run("parse", str(lp.root), "--doc", "scanned", "--force")
    assert r.returncode == 1, r.stdout + r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    err = [o for o in lines if o.get("status") == "error" and o.get("doc") == "scanned"]
    assert err and "2 decision(s)" in err[0]["detail"]
    assert "--discard-decisions" in err[0]["detail"]
    assert hashlib.sha256(blocks.read_bytes()).hexdigest() == before  # nothing re-parsed
    # a doc without decisions and a no-op parse are not refused
    r = run("parse", str(lp.root), "--doc", "clean")
    assert r.returncode == 0, r.stdout + r.stderr
    # `labor run` names the count too
    r = run("run", str(lp.root), "--to", "parse", "--doc", "scanned", "--force", "parse", "--mock")
    assert r.returncode == 1 and "2 decision(s)" in r.stdout


def test_a_failed_stage_records_its_actual_error_in_the_job_row(lp: ProjectPaths) -> None:
    lp.doc("clean").blocks.write_text("THIS IS NOT JSON\n", encoding="utf-8")
    store = Store.open(lp)
    try:
        res = run_inline(
            lp,
            RunPlanIn(to="score", docs=["clean"], force=["score"]),
            mode="mock",
            emit=lambda _o: None,
            store=store,
        )
        assert not res.ok
        row = store.job_rows()[-1]
        assert row["status"] == "failed"
        err = str(row["error"])
        # the first failing unit (blocks.json feeds figures first) with the exception text
        assert re.match(r"^figures clean: ValidationError: ", err), err
        assert "Invalid JSON" in err and len(err) <= 500
        # the same through the worker subprocess and the runner
        runner = JobRunner(lp, store, mode="mock")
        runner.start()
        try:
            job = runner.enqueue(RunPlanIn(to="score", docs=["clean"], force=["score"]))
            wait_for(lambda: runner.get(job.id).status in ("done", "failed", "interrupted"))
        finally:
            runner.stop()
        final = runner.get(job.id)
        assert final.status == "failed"
        assert final.error is not None
        assert re.match(r"^figures clean: ValidationError: ", final.error), final.error
        assert "Invalid JSON" in final.error and len(final.error) <= 500
    finally:
        store.close()


def test_learning_list_is_read_only_and_works_while_the_project_is_held(
    lp: ProjectPaths,
) -> None:
    Store.open(lp).close()  # the project has a database (serve creates it at start)
    db = lp.db.read_bytes()
    lock = ProjectLock(lp.lock, cmd="labor serve (test)")
    lock.acquire()
    try:
        r = run("learning", "list", str(lp.root))
        assert r.returncode == 0, r.stderr
        assert "provenance=baseline" in r.stdout
        r = run("learning", "snapshot", str(lp.root))  # writers still need the lock
        assert r.returncode == 3
    finally:
        lock.release()
    assert lp.db.read_bytes() == db
