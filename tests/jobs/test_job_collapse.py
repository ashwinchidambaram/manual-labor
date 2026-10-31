"""Design 07 section 18: a newly enqueued pipeline run folds into an identical job that is the
queue's tail and still queued, never into a running one. The folded row stays (status `merged`,
`merged_into`), mirrors the survivor's progress and ends with the survivor's outcome."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from manuallabor.jobs import runner as runner_mod
from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store

PLAN = RunPlanIn(to="score2", docs=["clean"])


class FakeProc:
    """A worker that never runs: the test writes its log and sets `returncode` to end it."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    paths = ProjectPaths(tmp_path / "p")
    paths.root.mkdir()
    s = Store.open(paths)
    yield s
    s.close()


@pytest.fixture
def procs(monkeypatch: pytest.MonkeyPatch) -> list[FakeProc]:
    made: list[FakeProc] = []

    def popen(*_a: Any, **_k: Any) -> FakeProc:
        p = FakeProc(4242 + len(made))
        made.append(p)
        return p

    monkeypatch.setattr(runner_mod.subprocess, "Popen", popen)
    monkeypatch.setattr(runner_mod.os, "setpriority", lambda *_a: None)
    return made


def _runner(store: Store, *, resume: bool = False) -> JobRunner:
    return JobRunner(store.paths, store, mode="mock", resume=resume)


def _log(paths: ProjectPaths, job_id: str, *events: dict[str, Any]) -> None:
    p = paths.job_log(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _ids(rows: list[Any]) -> list[str]:
    return [f"job-{r['n']:06d}" for r in rows]


def test_two_identical_enqueues_give_one_queued_job_and_one_merged_row(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    assert a.status == "queued" and a.merged_into is None
    assert b.status == "merged" and b.merged_into == a.id and b.id != a.id
    assert _ids(store.job_rows({"queued"})) == [a.id]
    assert [j.id for j in r.list({"queued", "running"})] == [a.id]
    assert not store.paths.job_plan(b.id).exists()  # never started: no plan file
    c = r.enqueue(PLAN)  # a third one folds into the same survivor (no chains)
    assert c.status == "merged" and c.merged_into == a.id


def test_a_running_job_is_never_merged_into(store: Store, procs: list[FakeProc]) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    r.poll()
    assert r.get(a.id).status == "running"
    b = r.enqueue(PLAN)
    assert b.status == "queued" and b.merged_into is None


def test_an_enqueue_while_the_worker_is_being_spawned_is_not_merged(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row says `running` before the process exists: a worker that may already be reading
    its inputs never absorbs a later change."""
    r = _runner(store)
    a = r.enqueue(PLAN)
    seen: dict[str, Any] = {}

    def popen(*_a: Any, **_k: Any) -> FakeProc:
        seen["status_at_spawn"] = store.job_row(a.id)["status"]  # type: ignore[index]
        seen["inner"] = r.enqueue(PLAN)
        return FakeProc()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", popen)
    monkeypatch.setattr(runner_mod.os, "setpriority", lambda *_a: None)
    r.poll()
    assert seen["status_at_spawn"] == "running"
    assert seen["inner"].status == "queued" and seen["inner"].merged_into is None
    assert r.get(a.id).pid == 4242


@pytest.mark.parametrize(
    "other",
    [
        RunPlanIn(to="group", docs=["clean"]),
        RunPlanIn(to="score2", docs=["scanned"]),
        RunPlanIn(to="score2", docs=["clean", "scanned"]),
        RunPlanIn(to="score2", docs=None),
        RunPlanIn(to="score2", docs=["clean"], force=["figures"]),
        RunPlanIn(to="score2", docs=["clean"], allow_reparse=True),
    ],
    ids=["to", "docs", "more-docs", "all-docs", "force", "allow_reparse"],
)
def test_a_plan_that_differs_in_any_field_is_not_merged(store: Store, other: RunPlanIn) -> None:
    r = _runner(store)
    r.enqueue(PLAN)
    assert r.enqueue(other).status == "queued"


def test_doc_order_is_part_of_the_plan(store: Store) -> None:
    r = _runner(store)
    r.enqueue(RunPlanIn(to="score2", docs=["clean", "scanned"]))
    assert r.enqueue(RunPlanIn(to="score2", docs=["scanned", "clean"])).status == "queued"


def test_only_pipeline_runs_collapse(store: Store) -> None:
    r = _runner(store)
    e1 = r.enqueue(RunPlanIn(to="export"), kind="export")
    e2 = r.enqueue(RunPlanIn(to="export"), kind="export")
    a1 = r.enqueue_raw({"items": [1]}, "agent")
    a2 = r.enqueue_raw({"items": [1]}, "agent")
    assert [j.status for j in (e1, e2, a1, a2)] == ["queued"] * 4
    # a run behind an identical-looking plan of another kind is not merged into it
    r.enqueue(RunPlanIn(to="export"), kind="export")
    assert r.enqueue(RunPlanIn(to="export")).status == "queued"


def test_an_identical_job_behind_a_different_tail_is_not_merged(store: Store) -> None:
    """Folding past a different job would run the work before it (see section 18)."""
    r = _runner(store)
    r.enqueue(PLAN)
    r.enqueue(RunPlanIn(to="group", docs=["clean"]))
    assert r.enqueue(PLAN).status == "queued"
    assert len(store.job_rows({"queued"})) == 3


def test_the_merged_row_mirrors_progress_and_completes_with_the_survivor(
    store: Store, procs: list[FakeProc]
) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()
    _log(
        store.paths, a.id,
        {"event": "job_start", "units": 2},
        {"event": "unit_start", "node": "clean", "doc": "clean", "index": 0},
        {"event": "unit_done", "node": "clean", "doc": "clean", "status": "done"},
        {"event": "unit_start", "node": "score2", "doc": "clean", "index": 1},
        {"event": "step", "node": "score2", "doc": "clean", "done": 5, "total": 10,
         "unit": "block"},
    )  # fmt: skip
    r.poll()
    sa, sb = r.get(a.id), r.get(b.id)
    assert sa.status == "running" and sb.status == "merged" and sb.merged_into == a.id
    assert sb.progress == sa.progress == 0.75
    assert (sb.units_done, sb.units_total, sb.node, sb.doc) == (1, 2, "score2", "clean")
    assert (sb.step_done, sb.step_total, sb.step_unit) == (5, 10, "block")
    assert sb.pid is None and sb.started_at is None
    assert [x.status for x in r.list() if x.id == b.id] == ["merged"]
    assert [x.progress for x in r.list() if x.id == b.id] == [0.75]
    _log(
        store.paths, a.id,
        {"event": "unit_done", "node": "score2", "doc": "clean", "status": "done"},
        {"event": "job_end", "status": "done", "failed": {}},
    )  # fmt: skip
    procs[0].returncode = 0
    r.poll()
    fa, fb = r.get(a.id), r.get(b.id)
    assert fa.status == fb.status == "done"
    assert fb.progress == 1.0 and fb.finished_at == fa.finished_at and fb.merged_into == a.id
    assert fb.units_done == fb.units_total == 2
    assert [x["event"] for x in r.log(b.id, 0)] == [x["event"] for x in r.log(a.id, 0)]
    assert len(procs) == 1  # one worker for both


def test_a_failed_survivor_fails_its_merged_rows(store: Store, procs: list[FakeProc]) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()
    _log(store.paths, a.id, {"event": "job_end", "status": "failed", "error": "boom"})
    procs[0].returncode = 1
    r.poll()
    fa, fb = r.get(a.id), r.get(b.id)
    assert fa.status == fb.status == "failed"
    assert fa.error == fb.error == "boom"


def test_cancelling_the_survivor_cancels_its_merged_rows(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    assert r.cancel(a.id).status == "cancelled"
    assert r.get(b.id).status == "cancelled"
    # the queue is empty again: a new identical job is a fresh queued job
    assert r.enqueue(PLAN).status == "queued"


def test_cancelling_the_running_survivor_cancels_its_merged_rows(
    store: Store, procs: list[FakeProc], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod.JobRunner, "_signal", staticmethod(lambda *_a: None))
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()
    r.cancel(a.id)
    _log(store.paths, a.id, {"event": "job_end", "status": "cancelled"})
    procs[0].returncode = -15
    r.poll()
    assert r.get(a.id).status == r.get(b.id).status == "cancelled"


def test_cancelling_a_merged_row_leaves_the_survivor_queued(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    assert r.cancel(b.id).status == "cancelled"
    assert r.get(a.id).status == "queued"


def _dead_running(store: Store, job_id: str) -> None:
    store.update_job(job_id, status="running", pid=2**22 + 12345, started_at=store.now())


def test_an_interrupted_survivor_hands_its_merged_rows_to_the_resumed_job(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    _dead_running(store, a.id)
    r2 = _runner(store, resume=True)
    r2._reconcile()
    assert r2.get(a.id).status == "interrupted"
    resumed = [j for j in r2.list({"queued"})]
    assert len(resumed) == 1 and resumed[0].resumed_from == a.id
    mb = r2.get(b.id)
    assert mb.status == "merged" and mb.merged_into == resumed[0].id


def test_a_resumed_job_that_folds_into_the_tail_hands_over_to_that_tail(
    store: Store, procs: list[FakeProc]
) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()  # a runs; b still merged into it
    c = r.enqueue(PLAN)  # queued behind the running a
    assert c.status == "queued"
    store.update_job(a.id, pid=2**22 + 12345)
    r2 = _runner(store, resume=True)
    r2._reconcile()
    assert r2.get(a.id).status == "interrupted"
    assert r2.get(b.id).merged_into == c.id and r2.get(b.id).status == "merged"
    assert _ids(store.job_rows({"queued"})) == [c.id]


def test_without_resume_the_oldest_merged_row_is_queued_again(store: Store) -> None:
    """Before section 18 those rows were queued jobs that still ran after a --no-resume start:
    the work is not dropped with the survivor."""
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN, request_id="rq-b")
    c = r.enqueue(PLAN)
    _dead_running(store, a.id)
    r2 = _runner(store, resume=False)
    r2._reconcile()
    assert r2.get(a.id).status == "interrupted"
    hb, hc = r2.get(b.id), r2.get(c.id)
    assert hb.status == "queued" and hb.merged_into is None
    assert hc.status == "merged" and hc.merged_into == b.id
    assert store.paths.job_plan(b.id).is_file()  # the worker's input exists now
    assert _ids(store.job_rows({"queued"})) == [b.id]
    assert r2.enqueue(PLAN, request_id="rq-b").id == b.id  # its request still replays to it


def test_a_cancelled_survivor_found_dead_at_start_cancels_its_merged_rows(store: Store) -> None:
    """Cancel, then serve died before the worker exited: the same outcome as mid-session."""
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    _dead_running(store, a.id)
    store.update_job(a.id, cancel_requested=1)
    for resume in (True, False):
        r2 = _runner(store, resume=resume)
        r2._reconcile()
        assert r2.get(a.id).status == r2.get(b.id).status == "cancelled"
        assert store.job_rows({"queued", "merged"}) == []


def test_a_worker_that_dies_mid_session_hands_the_work_to_a_merged_row(
    store: Store, procs: list[FakeProc]
) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()
    procs[0].returncode = -9  # no job_end line: interrupted
    r.poll()
    assert r.get(a.id).status == "interrupted"
    # queued again in the finalizing transaction, so the same tick starts it
    assert r.get(b.id).status == "running" and r.get(b.id).merged_into is None
    assert len(procs) == 2


def test_a_replay_shows_the_merged_row_as_get_does(store: Store, procs: list[FakeProc]) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN, request_id="rq-a")
    r.enqueue(PLAN, request_id="rq-b")
    r.poll()
    _log(store.paths, a.id, {"event": "job_start", "units": 4},
         {"event": "unit_done", "node": "clean", "doc": "clean", "status": "done"})  # fmt: skip
    r.poll()
    again = r.enqueue(PLAN, request_id="rq-b")
    assert again.progress == 0.25 and again == r.get(again.id)


def test_the_start_sweep_interrupts_a_merged_row_whose_survivor_is_gone(store: Store) -> None:
    with store.tx():
        jid = store.add_job(kind="run", plan={"to": "score2"}, merged_into="job-000999")
    r = _runner(store)
    r._reconcile()
    got = r.get(jid)
    assert got.status == "interrupted" and "job-000999" in (got.error or "")


def test_the_start_sweep_settles_a_merged_row_whose_survivor_ended(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    store.update_job(a.id, status="done", progress=1.0, finished_at=store.now())  # by hand
    r2 = _runner(store)
    r2._reconcile()
    assert r2.get(b.id).status == "done"


def test_a_spawn_failure_fails_the_job_and_its_merged_rows(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def popen(*_a: Any, **_k: Any) -> FakeProc:
        raise OSError("no such interpreter")

    monkeypatch.setattr(runner_mod.subprocess, "Popen", popen)
    r = _runner(store)
    a = r.enqueue(PLAN)
    b = r.enqueue(PLAN)
    r.poll()
    fa, fb = r.get(a.id), r.get(b.id)
    assert fa.status == fb.status == "failed"
    assert "no such interpreter" in (fa.error or "") and fb.error == fa.error
    assert store.job_rows({"queued", "running"}) == []


def test_request_id_replay_returns_the_first_response(store: Store) -> None:
    r = _runner(store)
    a = r.enqueue(PLAN, request_id="rq-a")
    b = r.enqueue(PLAN, request_id="rq-b")
    assert b.status == "merged" and b.merged_into == a.id
    assert r.enqueue(PLAN, request_id="rq-a") == a
    assert r.enqueue(PLAN, request_id="rq-b") == b
    assert len(store.job_rows()) == 2
    # each row keeps its own request id; the key ignores it
    assert json.loads(store.job_row(b.id)["plan"])["request_id"] == "rq-b"  # type: ignore[index]


def _plan(store: Store, query: str, args: tuple[object, ...]) -> str:
    rows = store.q("EXPLAIN QUERY PLAN " + query, args)
    return " | ".join(str(r["detail"]) for r in rows)


def test_the_lookups_use_their_indexes(store: Store) -> None:
    from manuallabor.state.store import MERGED_ROWS_SQL, QUEUE_HEAD_SQL, QUEUE_TAIL_SQL

    assert "jobs_status" in _plan(store, QUEUE_TAIL_SQL, ())
    assert "jobs_status" in _plan(store, QUEUE_HEAD_SQL, ())  # the tick's next job: one row
    assert "jobs_merged" in _plan(store, MERGED_ROWS_SQL, ("job-000001",))
    # the statements that settle and repoint merged rows at a job's end
    settle = "UPDATE jobs SET status=?, error=? WHERE merged_into=? AND status='merged'"
    assert "jobs_merged" in _plan(store, settle, ("done", None, "job-000001"))
    repoint = "UPDATE jobs SET merged_into=? WHERE merged_into=? AND status='merged'"
    assert "jobs_merged" in _plan(store, repoint, ("job-000002", "job-000001"))


def test_an_identical_enqueue_inside_a_transaction_beside_a_tick_collapses(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 16.5: the collapse uses the store transaction alone, never the runner's lock."""
    r = _runner(store)
    started: list[str] = []
    monkeypatch.setattr(r, "_start", started.append)
    a = r.enqueue(PLAN)
    in_tick = threading.Event()
    real_rows = store.job_rows

    def job_rows(*x: Any, **k: Any) -> Any:
        in_tick.set()
        return real_rows(*x, **k)

    monkeypatch.setattr(store, "job_rows", job_rows)
    done: dict[str, Any] = {}

    def tx_side() -> None:
        with store.tx():
            assert in_tick.wait(10)
            threading.Event().wait(0.2)
            done["job"] = r.enqueue(PLAN, request_id="rq-1")

    def tick_side() -> None:
        r.poll()
        done["tick"] = True

    t1 = threading.Thread(target=tx_side, daemon=True)
    t2 = threading.Thread(target=tick_side, daemon=True)
    t1.start()
    t2.start()
    t1.join(20)
    t2.join(20)
    assert done.get("tick") and "job" in done, f"deadlock: {done}"
    assert done["job"].status == "merged" and done["job"].merged_into == a.id
    assert started == [a.id]
