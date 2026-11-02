"""Only manuals in the selection can lock the export (design 07 section 21, design 11 section
20.18). First-time user run 5: two manuals that could not be read were deselected, the third was
reviewed, and the Export screen still said "Not ready to export: pump-service-tables.pdf,
x200-two-column.pdf ..." with no way out."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from manuallabor.export.pipeline import export_status, resolve_clock, run_export
from manuallabor.export.validate import validate_zip
from manuallabor.ingest import ingest_files
from manuallabor.jobs import graph
from manuallabor.jobs.executor import make_plan, make_project_plan
from manuallabor.project import ProjectPaths
from manuallabor.state.store import Store
from tests.conftest import FIXTURES, labor_copy
from tests.export.helpers import CLOCK, labor_run

STUCK = "manual"  # manual.docx, read up to scoring, then grouping failed (the service was down)
DOWN = "Ollama is not running at http://127.0.0.1:11434. Start it (`ollama serve`) and press Retry."


def fail_group(paths: ProjectPaths, slug: str) -> None:
    st = graph.load_stages(paths, slug)
    st.record("group", "failed", None, DOWN, code="provider_unreachable")
    graph.save_stages(paths, slug, st)


@pytest.fixture(scope="session")
def stuck_a(approved_a: ProjectPaths, tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    """project-a, fully approved, plus a third manual that never got past `group`."""
    root = tmp_path_factory.mktemp("export-stuck") / "proj"
    paths = ProjectPaths(labor_copy(approved_a.root, root, db=True))
    # the copy shares the read-only sources dir: give this project its own
    src = paths.root / "sources"
    target = src.resolve()
    src.unlink()
    src.mkdir()
    for p in target.iterdir():
        (src / p.name).write_bytes(p.read_bytes())
    ingest_files(paths, [FIXTURES / "manual.docx"], emit=lambda _o: None)
    labor_run(paths.root, "--to", "score")
    fail_group(paths, STUCK)
    assert not paths.doc(STUCK).groups.exists()
    return paths


@pytest.fixture
def stuck(stuck_a: ProjectPaths, tmp_path: Path) -> ProjectPaths:
    dst = tmp_path / "proj"
    import shutil

    shutil.copytree(stuck_a.root, dst, ignore=shutil.ignore_patterns("logs", ".labor*.lock"))
    return ProjectPaths(dst)


def test_a_failed_manual_outside_the_selection_does_not_lock_the_export(
    stuck: ProjectPaths,
) -> None:
    store = Store.open(stuck)
    try:
        st = export_status(stuck, store)
        assert st.not_ready == [], st.not_ready
        assert st.unlocked is True and st.blockers == []
        rec = run_export(stuck, store, clock=resolve_clock(CLOCK), emit=lambda _o: None)
    finally:
        store.close()
    zp = Path(rec.zip_path)
    assert validate_zip(zp) == []
    with zipfile.ZipFile(zp) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    docs = {d["slug"] for d in manifest["docs"]}
    assert docs == {"clean", "figures", STUCK}
    stuck_ids = stuck.load_document(STUCK).block_ids
    assert stuck_ids, "the stuck manual was parsed: its blocks must be accounted for"
    acc = manifest["accounting"]
    for bid in stuck_ids:
        assert acc["assignments"][bid] == "unassigned"
        assert acc["unassigned_reasons"][bid] == "not_selected"
    assert acc["total_blocks"] == len(acc["assignments"])
    assert not [a for a in manifest["articles"] if a["source_doc"] == STUCK]


def test_a_grouped_manual_in_the_selection_still_locks_it(stuck: ProjectPaths) -> None:
    """The same manual once grouped (the service came back) arrives selected (design 08
    section 10) and is in scope: not scored and cleaned yet, so the export waits for it."""
    labor_run(stuck.root, "--to", "group")
    assert stuck.doc(STUCK).groups.is_file()
    store = Store.open(stuck)
    try:
        st = export_status(stuck, store)
    finally:
        store.close()
    assert st.not_ready == [STUCK] and st.unlocked is False


def test_score2_plans_leave_out_a_failed_manual_outside_the_selection(stuck: ProjectPaths) -> None:
    cfg = stuck.load_config()
    plan = make_plan(stuck, cfg, to="score2")
    assert STUCK not in {s for _n, s in plan.units} and plan.out_of_scope == [STUCK]
    project = make_project_plan(stuck, cfg, to="export")
    assert STUCK not in {s for _n, s in project.units} and project.out_of_scope == [STUCK]
    # Scope's Run / Re-run (to group) is how a stuck manual is retried: it stays in that plan
    regroup = make_plan(stuck, cfg, to="group")
    assert ("group", STUCK) in regroup.units and regroup.out_of_scope == []


def test_a_manual_still_being_read_stays_in_a_score2_plan(stuck: ProjectPaths) -> None:
    """No groups.json and no failure: grouping will put it in the selection, so it is planned."""
    st = graph.load_stages(stuck, STUCK)
    del st.nodes["group"]
    graph.save_stages(stuck, STUCK, st)
    plan = make_plan(stuck, stuck.load_config(), to="score2")
    assert ("group", STUCK) in plan.units and plan.out_of_scope == []


def test_labor_run_to_score2_succeeds_beside_a_failed_manual(stuck: ProjectPaths) -> None:
    labor_run(stuck.root, "--to", "score2")
    assert graph.load_stages(stuck, STUCK).nodes["group"].status == "failed"
