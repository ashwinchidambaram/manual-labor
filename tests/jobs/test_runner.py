"""G6, G7: the job runner (worker subprocess, supervision, cancel, adopt, auto-resume)."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store
from tests.conftest import labor_copy
from tests.jobs.test_resume import (
    assert_no_group_members,
    assert_resumed_equals,
    hash_map,
)


def wait_for(cond: Callable[[], bool], timeout: float = 180.0, step: float = 0.05) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(step)
    raise AssertionError("timed out")


def job_lines(paths: ProjectPaths, job_id: str) -> list[dict]:  # type: ignore[type-arg]
    p = paths.job_log(job_id)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
    return out


@pytest.fixture
def proj(labor_template: Path, tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(labor_copy(labor_template, tmp_path / "proj"))


def test_g6_job_lifecycle_progress_and_log(proj: ProjectPaths, labor_scored: Path) -> None:
    store = Store.open(proj)
    runner = JobRunner(proj, store, mode="mock")
    runner.start()
    try:
        job = runner.enqueue(RunPlanIn(to="score2"))
        assert job.status == "queued" and job.progress == 0.0
        seen: list[tuple[str, float]] = []

        def done() -> bool:
            j = runner.get(job.id)
            seen.append((j.status, j.progress))
            return j.status in ("done", "failed", "cancelled", "interrupted")

        wait_for(done)
    finally:
        runner.stop()
    final = runner.get(job.id)
    assert final.status == "done", final.error
    assert final.progress == 1.0 and final.units_done == final.units_total > 0
    statuses = [s for s, _ in seen]
    assert statuses.index("running") < statuses.index("done") if "running" in statuses else True
    progress = [p for _, p in seen]
    assert progress == sorted(progress) and all(0.0 <= p <= 1.0 for p in progress)
    events = [o.get("event") for o in job_lines(proj, job.id)]
    assert events[0] == "job_start" and events[-1] == "job_end" and "unit_done" in events
    assert final.node == "score2" and final.pid is not None
    msgs = runner.log(job.id, 0)
    assert msgs and msgs[0]["line"] == 0 and runner.log(job.id, 3)[0]["line"] == 3
    store.close()
    assert hash_map(proj) == hash_map(ProjectPaths(labor_scored))


def test_g6_cancel_during_clean_then_rerun(
    proj: ProjectPaths, labor_scored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANUALLABOR_DELAY", "node.before:clean:clean=4")
    store = Store.open(proj)
    runner = JobRunner(proj, store, mode="mock")
    runner.start()
    try:
        job = runner.enqueue(RunPlanIn(to="score2"))

        def reached_clean() -> bool:
            j = runner.get(job.id)
            return (
                j.status == "running"
                and (j.node, j.units_done) != (None, 0)
                and any(o.get("stage") == "group" for o in job_lines(proj, job.id))
            )

        wait_for(reached_clean)
        pid = runner.get(job.id).pid
        assert pid is not None
        pgid = os.getpgid(pid)
        runner.cancel(job.id)
        wait_for(lambda: runner.get(job.id).status in ("cancelled", "done", "failed"))
        assert runner.get(job.id).status == "cancelled"
        wait_for(
            lambda: subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True).returncode != 0
        )
        assert_no_group_members(pgid)
        monkeypatch.delenv("MANUALLABOR_DELAY")
        again = runner.enqueue(RunPlanIn(to="score2"))
        wait_for(lambda: runner.get(again.id).status in ("done", "failed", "cancelled"))
        assert runner.get(again.id).status == "done", runner.get(again.id).error
    finally:
        runner.stop()
        store.close()
    assert hash_map(proj) == hash_map(ProjectPaths(labor_scored))


def test_g6_cancel_a_queued_job_and_unknown_ids(proj: ProjectPaths) -> None:
    from manuallabor.state.errors import InvalidOp, NotFound

    store = Store.open(proj)
    runner = JobRunner(proj, store, mode="mock")  # not started: nothing runs
    job = runner.enqueue(RunPlanIn(to="group"))
    assert runner.cancel(job.id).status == "cancelled"
    with pytest.raises(InvalidOp):
        runner.cancel(job.id)
    with pytest.raises(NotFound):
        runner.get("job-999999")
    assert [j.id for j in runner.list({"cancelled"})] == [job.id]
    store.close()


def start_supervisor(proj: ProjectPaths, enqueue: bool) -> subprocess.Popen[str]:
    p = subprocess.Popen(
        [sys.executable, "-m", "tests.jobs.children", "supervisor", str(proj.root), "mock",
         "yes" if enqueue else "no"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )  # fmt: skip
    assert p.stdout is not None
    while True:
        line = p.stdout.readline()
        assert line, "supervisor exited early"
        if line.strip() == "ready":
            return p


def db_job(proj: ProjectPaths, n: int) -> dict:  # type: ignore[type-arg]
    s = Store.open(proj, readonly=True)
    try:
        r = s.job_row(f"job-{n:06d}")
        return dict(r) if r is not None else {}
    finally:
        s.close()


def worker_log_has(proj: ProjectPaths, job_id: str, pred: Callable[[dict], bool]) -> bool:  # type: ignore[type-arg]
    return any(pred(o) for o in job_lines(proj, job_id))


def test_r5_supervisor_killed_the_worker_survives_and_is_adopted(
    proj: ProjectPaths, labor_scored: Path
) -> None:
    sup = start_supervisor(proj, enqueue=True)
    try:
        wait_for(
            lambda: worker_log_has(proj, "job-000001", lambda o: o.get("event") == "job_start")
        )
        pid = db_job(proj, 1)["pid"]
        os.kill(sup.pid, signal.SIGKILL)  # only the supervisor
        sup.wait()
    finally:
        if sup.poll() is None:
            sup.kill()
    second = start_supervisor(proj, enqueue=False)
    try:
        wait_for(lambda: db_job(proj, 1)["status"] in ("done", "failed", "interrupted"))
        row = db_job(proj, 1)
        assert row["status"] == "done", row
        assert row["pid"] == pid  # the same worker finished it: adopted, not restarted
        assert db_job(proj, 2) == {}
    finally:
        second.kill()
        second.wait()
    assert_resumed_equals(proj, ProjectPaths(labor_scored))


def test_r6_supervisor_and_worker_killed_the_job_resumes(
    proj: ProjectPaths, labor_scored: Path
) -> None:
    sup = start_supervisor(proj, enqueue=True)
    try:
        wait_for(lambda: worker_log_has(proj, "job-000001", lambda o: o.get("node") == "score"))
        pid = db_job(proj, 1)["pid"]
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        os.kill(sup.pid, signal.SIGKILL)
        sup.wait()
    finally:
        if sup.poll() is None:
            sup.kill()
    wait_for(
        lambda: subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True).returncode != 0, 30
    )
    second = start_supervisor(proj, enqueue=False)
    try:
        wait_for(lambda: db_job(proj, 2).get("status") in ("done", "failed", "interrupted"))
        old, new = db_job(proj, 1), db_job(proj, 2)
        assert old["status"] == "interrupted"
        assert new["status"] == "done" and new["resumed_from"] == "job-000001", new
    finally:
        second.kill()
        second.wait()
    assert_resumed_equals(proj, ProjectPaths(labor_scored))


def test_a_killed_cli_run_is_marked_interrupted_not_resumed(proj: ProjectPaths) -> None:
    store = Store.open(proj)
    cli_job = store.add_job(kind="run", plan={"to": "score2", "origin": "cli"})
    served = store.add_job(kind="run", plan={"to": "score2"})
    for j in (cli_job, served):
        store.update_job(j, status="running", pid=2**22 + 7, started_at=store.now())
    runner = JobRunner(proj, store, mode="mock", resume=True)
    runner._reconcile()
    jobs = {j.id: j for j in runner.list()}
    assert jobs[cli_job].status == "interrupted" and jobs[served].status == "interrupted"
    resumed = [j for j in jobs.values() if j.resumed_from]
    assert [j.resumed_from for j in resumed] == [served]  # only the serve-owned job resumes
    assert resumed[0].status == "queued"
    store.close()
