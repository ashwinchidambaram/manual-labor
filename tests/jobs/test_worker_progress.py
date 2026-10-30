"""Inner progress for the jobs bar (design 07 section 4.1): the worker names the unit it is on
(`unit_start`) and how far it is through it (`step`), the supervisor turns that into the job row,
and stages report only counts they already keep."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from manuallabor.grouping.pipeline import group_document
from manuallabor.jobs import progress
from manuallabor.jobs.runner import JobRunner
from manuallabor.jobs.worker import StepLog
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store
from tests.grouping.conftest import doc_of, heading, mk, provider_set

UNITS = [("parse", "a"), ("parse", "b"), ("figures", "a"), ("figures", "b")]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _tracker() -> tuple[StepLog, list[dict[str, Any]], Clock]:
    lines: list[dict[str, Any]] = []
    clock = Clock()
    return StepLog(lines.append, UNITS, clock=clock), lines, clock


def _events(lines: list[dict[str, Any]], kind: str) -> list[tuple[Any, ...]]:
    keys = ("node", "doc", "done", "total", "unit") if kind == "step" else ("node", "doc", "index")
    return [tuple(o.get(k) for k in keys) for o in lines if o.get("event") == kind]


def test_report_without_a_reporter_is_a_noop() -> None:
    assert progress.set_reporter(None) is None
    progress.report("a", 1, 2, "page")  # no worker: nothing happens, nothing raises


def test_worker_names_each_unit_before_it_runs() -> None:
    log, lines, _ = _tracker()
    log({"event": "job_start", "units": 4})
    assert _events(lines, "unit_start") == [("parse", "a", 0)]
    log({"doc": "a", "stage": "parse", "status": "done", "node": "parse"})
    log({"event": "unit_done", "node": "parse", "doc": "a", "status": "done"})
    # a unit the executor skips as blocked emits no unit_done, only its blocked line
    log({"doc": "b", "stage": "parse", "status": "blocked", "node": "parse"})
    log({"event": "unit_done", "node": "figures", "doc": "a", "status": "done"})
    assert _events(lines, "unit_start") == [
        ("parse", "a", 0),
        ("parse", "b", 1),
        ("figures", "a", 2),
        ("figures", "b", 3),
    ]
    log({"event": "unit_done", "node": "figures", "doc": "b", "status": "done"})
    assert len(_events(lines, "unit_start")) == 4  # nothing after the last unit


def test_steps_are_real_counts_of_the_current_unit_throttled_and_monotonic() -> None:
    log, lines, clock = _tracker()
    log({"event": "job_start", "units": 4})
    log.step("a", 1, 6, "page")
    log.step("a", 2, 6, "page")  # same instant: throttled
    clock.t = 0.3
    log.step("a", 3, 6, "page")
    clock.t = 0.35
    log.step("a", 2, 6, "page")  # never backwards
    log.step("b", 1, 6, "page")  # not the current unit: ignored
    log.step("a", 6, 6, "page")  # the last count is always written
    assert _events(lines, "step") == [
        ("parse", "a", 1, 6, "page"),
        ("parse", "a", 3, 6, "page"),
        ("parse", "a", 6, 6, "page"),
    ]
    log({"event": "unit_done", "node": "parse", "doc": "a", "status": "done"})
    log.step("b", 1, 4, "page")  # the next unit starts counting afresh
    assert _events(lines, "step")[-1] == ("parse", "b", 1, 4, "page")


@pytest.fixture
def runner(tmp_path: Path) -> tuple[JobRunner, Store, ProjectPaths]:
    paths = ProjectPaths(tmp_path / "proj")
    paths.root.mkdir(parents=True)
    store = Store.open(paths)
    return JobRunner(paths, store, mode="mock"), store, paths


def _running(store: Store, paths: ProjectPaths, kind: str = "run") -> str:
    job_id = store.add_job(kind=kind, plan={"to": "group"})
    store.update_job(job_id, status="running", pid=os.getpid(), started_at=store.now())
    paths.job_log(job_id).parent.mkdir(parents=True, exist_ok=True)
    return job_id


def _write(paths: ProjectPaths, job_id: str, *objs: dict[str, Any]) -> None:
    with open(paths.job_log(job_id), "a", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o) + "\n")


def test_job_row_names_the_current_step_and_advances_within_it(
    runner: tuple[JobRunner, Store, ProjectPaths],
) -> None:
    r, store, paths = runner
    job_id = _running(store, paths)
    _write(
        paths,
        job_id,
        {"event": "job_start", "units": 4},
        {"event": "unit_start", "node": "parse", "doc": "a", "index": 0},
        {"event": "unit_done", "node": "parse", "doc": "a", "status": "done"},
        {"event": "unit_start", "node": "figures", "doc": "a", "index": 1},
    )
    r.poll()
    j = r.get(job_id)
    # the current unit, not the last finished one; no inner count yet
    assert (j.node, j.doc, j.units_done, j.units_total) == ("figures", "a", 1, 4)
    assert (j.step_done, j.step_total, j.step_unit) == (None, None, None)
    assert j.progress == pytest.approx(0.25)

    _write(
        paths,
        job_id,
        {"event": "step", "node": "figures", "doc": "a", "done": 4, "total": 6, "unit": "page"},
    )
    r.poll()
    j = r.get(job_id)
    assert (j.step_done, j.step_total, j.step_unit) == (4, 6, "page")
    assert j.progress == pytest.approx((1 + 4 / 6) / 4)
    assert [x for x in r.list({"running"}) if x.id == job_id][0].step_done == 4

    # a step of another unit is not this unit's progress
    _write(
        paths,
        job_id,
        {"event": "step", "node": "score", "doc": "b", "done": 1, "total": 2, "unit": "block"},
    )
    r.poll()
    assert r.get(job_id).step_done == 4

    _write(
        paths,
        job_id,
        {"event": "unit_done", "node": "figures", "doc": "a", "status": "done"},
        {"event": "unit_start", "node": "group", "doc": "a", "index": 2},
    )
    r.poll()
    j = r.get(job_id)
    assert (j.node, j.doc, j.units_done, j.step_done) == ("group", "a", 2, None)
    assert j.progress == pytest.approx(0.5)  # never moves back


def test_ingest_job_names_its_files_while_queued(
    runner: tuple[JobRunner, Store, ProjectPaths], tmp_path: Path
) -> None:
    r, _, _ = runner
    f = tmp_path / "x200-two-column.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    job = r.enqueue(RunPlanIn(to="group"), kind="ingest_run", files=[f])
    assert job.files == ["x200-two-column.pdf"]
    assert r.list({"queued"})[0].files == ["x200-two-column.pdf"]


def test_topic_naming_reports_topics_named() -> None:
    blocks = []
    for p in range(1, 7):
        blocks.append(heading(p, 1, f"{p}. Section {p}"))
        blocks += [
            mk(p, n, f"Words about part {p} item {n} torque {n * p} N·m.") for n in range(2, 14)
        ]
    got: list[tuple[str, int, int, str]] = []
    prev = progress.set_reporter(lambda d, a, b, u: got.append((d, a, b, u)))
    try:
        gf = group_document(doc_of(blocks), blocks, provider_set(ListSink()))
    finally:
        progress.set_reporter(prev)
    named = [g for g in got if g[3] == "topic"]
    assert named, got
    total = named[0][2]
    assert [g[1] for g in named] == list(range(1, total + 1))
    assert all(g[0] == "doc" and g[2] == total for g in named)
    assert total >= 1 and gf.topic_status == "ok"


def _collect(fn: Any) -> list[tuple[str, int, int, str]]:
    got: list[tuple[str, int, int, str]] = []
    prev = progress.set_reporter(lambda d, a, b, u: got.append((d, a, b, u)))
    try:
        fn()
    finally:
        progress.set_reporter(prev)
    return got


def test_scoring_and_cleanup_report_blocks_done() -> None:
    from manuallabor.cleanup.pipeline import clean_document
    from manuallabor.scoring.pipeline import score_document

    blocks = [mk(1, n, f"Torque {n} N·m.") for n in range(1, 6)]
    d = doc_of(blocks)
    scored = _collect(lambda: score_document(d, blocks, [], {}, {}, 0.8))
    assert scored == [("doc", i, 5, "block") for i in range(1, 6)]
    cleaned = _collect(lambda: clean_document(d, blocks, [], {b.id for b in blocks}, mode="off"))
    # cleanup counts the blocks done before each one, then the last
    assert cleaned == [("doc", i, 5, "block") for i in range(6)]


def test_a_blocked_project_unit_is_announced_done_only_by_its_unit_done() -> None:
    """A project-level unit (assemble, export) writes its blocked line and then its own
    `unit_done`; the next unit is named only after that (backend review 2 finding 7). Advancing on
    the blocked line named `export` while the runner still read `assemble`'s lines."""
    lines: list[dict[str, Any]] = []
    log = StepLog(lines.append, [("parse", "a"), ("assemble", ""), ("export", "")])
    log({"event": "job_start", "units": 3})
    log({"doc": "a", "stage": "parse", "status": "error", "node": "parse"})
    log({"event": "unit_done", "node": "parse", "doc": "a", "status": "failed"})
    assert _events(lines, "unit_start")[-1] == ("assemble", "", 1)
    log({"doc": "", "stage": "assemble", "status": "blocked", "node": "assemble"})
    assert _events(lines, "unit_start")[-1] == ("assemble", "", 1)  # still the blocked unit
    log({"event": "unit_done", "node": "assemble", "doc": "", "status": "blocked"})
    assert _events(lines, "unit_start")[-1] == ("export", "", 2)
    log({"doc": "", "stage": "export", "status": "blocked", "node": "export"})
    log({"event": "unit_done", "node": "export", "doc": "", "status": "blocked"})
    assert _events(lines, "unit_start") == [
        ("parse", "a", 0),
        ("assemble", "", 1),
        ("export", "", 2),
    ]
