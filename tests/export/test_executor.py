"""The project-level nodes `assemble` and `export` in the executor (design 11 C4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuallabor.jobs import graph
from manuallabor.jobs.executor import PROJECT_NODES, execute, make_plan, make_project_plan
from manuallabor.project import ProjectPaths


def test_make_project_plan_appends_project_units_after_every_document_unit(
    work: ProjectPaths,
) -> None:
    cfg = work.load_config()
    plan = make_project_plan(work, cfg, to="export")
    assert plan.units == [("assemble", ""), ("export", "")]  # nothing stale: no document units
    assert make_project_plan(work, cfg, to="assemble").units == [("assemble", "")]
    assert make_project_plan(work, cfg, to="export", force=["export"]).force == ["export"]
    with pytest.raises(ValueError, match="assemble, export"):
        make_project_plan(work, cfg, to="score2")
    with pytest.raises(ValueError):  # module 7's planner still refuses project nodes
        make_plan(work, cfg, to="export")
    assert PROJECT_NODES == ("assemble", "export")


def test_stale_documents_come_first(work: ProjectPaths) -> None:
    work.doc("clean").groups.unlink()
    plan = make_project_plan(work, work.load_config(), to="export")
    assert plan.units[-2:] == [("assemble", ""), ("export", "")]
    assert all(s == "clean" for _n, s in plan.units[:-2]) and len(plan.units) > 2


def test_execute_runs_the_units_and_reports_them(
    work: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANUALLABOR_NOW", "2026-10-29T12:00:00Z")
    lines: list[dict[str, object]] = []
    plan = make_project_plan(work, work.load_config(), to="export")
    done: list[tuple[str, str, str]] = []
    res = execute(work, plan, emit=lines.append, providers=None, on_unit=lambda *a: done.append(a))
    assert res.ok and res.units_done == 2
    assert done == [("assemble", "", "done"), ("export", "", "done")]
    stage_lines = [(o["stage"], o["status"], o["node"]) for o in lines if "stage" in o]
    assert ("assemble", "built", "assemble") in stage_lines and (
        "export",
        "built",
        "export",
    ) in stage_lines
    assert work.zip_path.is_file()
    states = {s.node: s.state for s in graph.project_node_states(work)}
    assert states == {"assemble": "fresh", "export": "fresh"}
    # a second run skips both
    lines.clear()
    res = execute(work, plan, emit=lines.append, providers=None)
    assert res.ok and {o["status"] for o in lines if "stage" in o} == {"skip"}
    assert [o["node"] for o in lines if o.get("event") == "unit_done"] == ["assemble", "export"]


def test_a_locked_gate_fails_the_unit_with_the_blockers(unreviewed: ProjectPaths) -> None:
    lines: list[dict[str, object]] = []
    plan = make_project_plan(unreviewed, unreviewed.load_config(), to="export")
    res = execute(unreviewed, plan, emit=lines.append, providers=None)
    assert not res.ok and res.failed == {"assemble": [""]} and res.blocked == {"export": [""]}
    locked = next(o for o in lines if o.get("status") == "locked")
    assert locked["blockers"] and "export is locked" in json.dumps(lines)
    assert not unreviewed.assembled.exists()


def test_a_failed_document_blocks_the_project_units(
    work: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuallabor.jobs.executor import ExecResult, Plan

    # run the tail of a plan whose document unit failed: the export must not start
    plan = Plan(units=[("assemble", ""), ("export", "")], to="export")
    import manuallabor.jobs.executor as ex

    seen: list[str] = []
    orig = ex._project_unit

    def spy(paths: ProjectPaths, node: str, plan: Plan, emit, res: ExecResult, *a):  # type: ignore[no-untyped-def]
        res.failed["clean"] = ["x"]  # as if a document unit had failed before this one
        seen.append(node)
        return orig(paths, node, plan, emit, res, *a)

    monkeypatch.setattr(ex, "_project_unit", spy)
    res = execute(work, plan, emit=lambda _o: None, providers=None)
    assert seen == ["assemble", "export"] and not res.ok
    assert res.blocked == {"assemble": [""], "export": [""]}
    assert not Path(work.zip_path).exists()


def test_node_states_are_missing_before_the_first_export(work: ProjectPaths) -> None:
    assert [s.state for s in graph.project_node_states(work)] == ["missing", "missing"]
