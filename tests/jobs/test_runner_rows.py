"""Review F8: the runner reads job rows by status in SQL, finds a replayed request by index,
writes progress only when it changed, and prunes old finished rows."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from manuallabor.jobs import runner as runner_mod
from manuallabor.jobs.runner import PRUNE_AFTER, PRUNE_KEEP, JobRunner, _Tail
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import utc_now
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store, fmt_ts


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    paths = ProjectPaths(tmp_path / "p")
    paths.root.mkdir()
    s = Store.open(paths)
    yield s
    s.close()


def _plan(store: Store, query: str, args: tuple[object, ...]) -> str:
    rows = store.q("EXPLAIN QUERY PLAN " + query, args)
    return " | ".join(str(r["detail"]) for r in rows)


def _add(store: Store, n: int, status: str, finished: str | None = None) -> list[str]:
    ids = []
    with store.tx():
        for i in range(n):
            jid = store.add_job(kind="run", plan={"to": "score2", "request_id": f"{status}-{i}"})
            if status != "queued":
                store.update_job(jid, status=status, finished_at=finished)
            ids.append(jid)
    return ids


def test_job_rows_filter_by_status_in_sql_through_the_index(store: Store) -> None:
    done = _add(store, 5, "done", fmt_ts(utc_now()))
    queued = _add(store, 2, "queued")
    assert [f"job-{r['n']:06d}" for r in store.job_rows({"queued"})] == queued
    assert [f"job-{r['n']:06d}" for r in store.job_rows({"done", "queued"})] == done + queued
    assert store.job_rows(set()) == []
    assert len(store.job_rows()) == 7
    plan = _plan(store, "SELECT * FROM jobs WHERE status IN (?) ORDER BY n", ("running",))
    assert "jobs_status" in plan, plan


def test_a_replayed_request_finds_its_job_by_index_without_parsing_plans(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add(store, 50, "done", fmt_ts(utc_now()))
    runner = JobRunner(store.paths, store, mode="mock", resume=False)
    first = runner.enqueue(RunPlanIn(to="group"), request_id="rq-1")
    calls = 0
    real = json.loads

    def counting(s: str | bytes, *a: object, **kw: object) -> object:
        nonlocal calls
        calls += 1
        return real(s, *a, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(runner_mod.json, "loads", counting)
    again = runner.enqueue(RunPlanIn(to="group"), request_id="rq-1")
    assert again.id == first.id
    assert calls == 1  # only the found job's own plan (job_info), not one per row
    assert len(store.job_rows()) == 51
    q = "SELECT * FROM jobs WHERE json_extract(plan, '$.request_id') = ? ORDER BY n LIMIT 1"
    assert "jobs_request" in _plan(store, q, ("rq-1",))


def test_an_unchanged_tick_writes_nothing(store: Store) -> None:
    runner = JobRunner(store.paths, store, mode="mock", resume=False)
    job = runner.enqueue(RunPlanIn(to="group"))
    tail = _Tail()
    tail.units_total, tail.units_done, tail.node = 4, 1, "parse"
    runner._update_progress(job.id, tail)
    assert runner.get(job.id).units_done == 1
    n = store.conn.total_changes
    runner._update_progress(job.id, tail)
    assert store.conn.total_changes == n
    tail.units_done = 2
    runner._update_progress(job.id, tail)
    assert store.conn.total_changes == n + 1
    assert runner.get(job.id).progress == 0.5


def test_prune_drops_old_finished_rows_beyond_the_newest_kept(store: Store) -> None:
    now = utc_now()
    old = fmt_ts(now - PRUNE_AFTER - timedelta(hours=1))
    recent = fmt_ts(now - PRUNE_AFTER + timedelta(hours=1))
    old_ids = _add(store, PRUNE_KEEP + 30, "done", old)
    old_failed = _add(store, 5, "failed", old)
    recent_ids = _add(store, 10, "cancelled", recent)
    queued = _add(store, 3, "queued")
    runner = JobRunner(store.paths, store, mode="mock", resume=False)
    # the newest PRUNE_KEEP finished rows stay whatever their age: 10 recent + 190 old
    kept_old = PRUNE_KEEP - len(recent_ids)
    removed = runner.prune()
    assert removed == len(old_ids) + len(old_failed) - kept_old
    left = {f"job-{r['n']:06d}" for r in store.job_rows()}
    assert set(queued) <= left and set(recent_ids) <= left
    survivors = sorted(left & set(old_ids + old_failed))
    assert survivors == sorted((old_ids + old_failed)[-kept_old:])
    assert runner.prune() == 0  # idempotent
    # a replayed request of a kept row still returns its job; a new request id still enqueues
    rid = json.loads(store.job_row(recent_ids[0])["plan"])["request_id"]  # type: ignore[index]
    assert runner.enqueue(RunPlanIn(to="group"), request_id=rid).id == recent_ids[0]


def test_the_worker_runs_below_the_server_priority(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CPU-bound parse must not starve the API (T13 on a 2-vCPU runner)."""
    calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(runner_mod.os, "setpriority", lambda *a: calls.append(a))

    class _Proc:
        pid = 4242
        returncode = None

        def poll(self) -> None:
            return None

    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **kw: _Proc())
    runner = JobRunner(store.paths, store, mode="mock", resume=False)
    job = runner.enqueue(RunPlanIn(to="group"))
    runner.poll()
    assert runner.get(job.id).status == "running"
    assert calls == [(runner_mod.os.PRIO_PROCESS, 4242, runner_mod.WORKER_NICE)]
