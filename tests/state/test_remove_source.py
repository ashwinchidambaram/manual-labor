"""Removing a manual (design 07 section 22, design 08 section 11). First-time user run 5: two
manuals that could not be read could not be removed or replaced from anywhere."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manuallabor.cli import app
from manuallabor.ingest import ingest_files
from manuallabor.jobs import graph
from manuallabor.jobs.render import render_status
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import Conflict, NotFound
from manuallabor.state.models import ActionKind, FlagIn, ReviewActionIn, SelectionOp
from manuallabor.state.sources import removal, remove_source
from manuallabor.state.store import Store
from tests.state.helpers import Env

GONE = "scanned"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))


def own_sources(paths: ProjectPaths) -> None:
    """`lp` shares a read-only sources dir; removal deletes a source file, so copy them."""
    src = paths.root / "sources"
    if src.is_symlink():
        target = src.resolve()
        src.unlink()
        shutil.copytree(target, src)


def reviewed(paths: ProjectPaths) -> tuple[Env, str, str]:
    """A decision and an open flag on the manual to be removed, and one decision on the other."""
    own_sources(paths)
    env = Env(paths)
    # a stored selection (with known_docs): one block of the other manual left out
    other = sorted(b for b in env.data.selection().block_ids if "-clean-" in b)[-1]
    env.scope.apply(SelectionOp(op="deselect", block_ids=[other], request_id="t-sel"))
    items = env.review.queue(None, None, GONE, 5, 0).items
    approved, flagged = items[0].block_id, items[1].block_id
    env.act("approve", approved)
    env.review.act(
        ReviewActionIn(
            kind="flag",
            block_id=flagged,
            flag=FlagIn(category="wrong_text", note="odd"),  # type: ignore[arg-type]
            request_id="t-flag",
        )
    )
    keep = env.review.queue(None, None, "clean", 1, 0).items[0].block_id
    env.act("approve", keep)
    return env, approved, flagged


def test_the_preview_states_what_is_at_stake(lp: ProjectPaths) -> None:
    env, _a, _f = reviewed(lp)
    try:
        p = removal(lp, env.store, GONE)
        doc = lp.load_document(GONE)
        assert (p.doc_id, p.filename, p.blocks) == (GONE, doc.filename, len(doc.block_ids))
        assert p.selected_blocks == sum(
            1 for b in env.data.selection().block_ids if f"-{GONE}-" in b
        )
        assert (p.decisions, p.open_flags, p.flags, p.removed) == (2, 1, 1, False)
        assert p.blocked_by is None
        with pytest.raises(NotFound):
            removal(lp, env.store, "no-such-manual")
    finally:
        env.close()


def test_removal_deletes_the_files_recounts_the_selection_and_orphans_the_log(
    lp: ProjectPaths,
) -> None:
    env, approved, flagged = reviewed(lp)
    try:
        doc = lp.load_document(GONE)
        decisions_before = len(env.store.decisions())
        flags_before = [f.id for f in env.store.flags()]
        out = remove_source(lp, env.store, GONE, "t-remove")
        assert out.removed and out.decisions == 2 and out.open_flags == 1
        # files
        assert GONE not in lp.list_slugs()
        assert not lp.doc(GONE).root.exists() and not lp.figure_dir(GONE).exists()
        assert not lp.source(doc.filename).exists()
        assert not [p for p in lp.docs.iterdir() if p.name.startswith(".removed-")]
        index = json.loads(lp.figures_index.read_text(encoding="utf-8"))
        assert not [e for e in index["entries"] if GONE in json.dumps(e)]
        # selection: its blocks and its known_docs entry are gone, the rest kept
        sel = env.data.selection()
        assert not [b for b in sel.block_ids if f"-{GONE}-" in b]
        assert [b for b in sel.block_ids if "-clean-" in b]
        raw = env.data.raw_selection()
        assert raw is not None and GONE not in (raw.known_docs or [])
        projected = json.loads(lp.selection.read_text(encoding="utf-8"))
        assert not [b for b in projected["block_ids"] if f"-{GONE}-" in b]
        assert GONE not in (projected.get("known_docs") or [])
        # the log is append-only: nothing deleted, the decisions and flag are orphaned
        assert len(env.store.decisions()) == decisions_before
        assert [f.id for f in env.store.flags()] == flags_before
        kinds = [a.kind for a in env.store.iter_actions()]
        assert kinds.count(ActionKind.remove_source) == 1
        st = graph.project_status(lp, None)
        assert [(r.doc_id, r.orphaned_decisions, r.open_flags) for r in st.removed] == [
            (GONE, 2, 1)
        ]
        assert "removed: scanned.pdf (scanned): 2 orphaned decisions, 1 open flag" in render_status(
            st, verbose=False
        )
        # a replay returns the first outcome and does nothing more
        again = remove_source(lp, env.store, GONE, "t-remove")
        assert again == out
        assert [a.kind for a in env.store.iter_actions()].count(ActionKind.remove_source) == 1
        with pytest.raises(NotFound):
            remove_source(lp, env.store, GONE, "t-remove-2")
    finally:
        env.close()


def test_the_rest_exports_after_a_removal(lp: ProjectPaths) -> None:
    from manuallabor.export.pipeline import export_status, resolve_clock, run_export
    from manuallabor.export.validate import validate_zip
    from tests.export.helpers import approve_queued, labor_run

    env, _a, _f = reviewed(lp)
    try:
        remove_source(lp, env.store, GONE, "t-remove")
    finally:
        env.close()
    labor_run(lp.root, "--to", "score2")  # the selection changed: cleanup settles it
    env = Env(lp)
    try:
        approve_queued(lp, env.store)
        st = export_status(lp, env.store)
        assert st.unlocked and st.not_ready == [] and st.open_flags == 0, st
        rec = run_export(
            lp, env.store, clock=resolve_clock("2026-11-02T12:00:00Z"), emit=lambda _o: None
        )
        assert validate_zip(Path(rec.zip_path)) == []
    finally:
        env.close()


def test_a_removal_is_refused_while_a_job_could_touch_the_manual(lp: ProjectPaths) -> None:
    from manuallabor.state.models import RunPlanIn

    env, _a, _f = reviewed(lp)
    try:
        jid = env.store.add_job(kind="run", plan=RunPlanIn(to="score2").model_dump(mode="json"))
        assert removal(lp, env.store, GONE).blocked_by is not None
        with pytest.raises(Conflict):
            remove_source(lp, env.store, GONE, "t-remove")
        assert GONE in lp.list_slugs()
        # a queued job for the other manual only does not touch this one
        env.store.update_job(jid, status="done")
        env.store.add_job(
            kind="run", plan=RunPlanIn(to="score2", docs=["clean"]).model_dump(mode="json")
        )
        assert removal(lp, env.store, GONE).blocked_by is None
        # any running job refuses: a worker writes project-wide files whatever its documents
        other = env.store.add_job(
            kind="run", plan=RunPlanIn(to="score2", docs=["clean"]).model_dump(mode="json")
        )
        env.store.update_job(other, status="running")
        assert removal(lp, env.store, GONE).blocked_by is not None
    finally:
        env.close()


def test_finished_job_rows_of_only_this_manual_are_dropped(lp: ProjectPaths) -> None:
    from manuallabor.state.models import RunPlanIn

    env, _a, _f = reviewed(lp)
    try:
        mine = env.store.add_job(
            kind="run", plan=RunPlanIn(to="group", docs=[GONE]).model_dump(mode="json")
        )
        wide = env.store.add_job(kind="run", plan=RunPlanIn(to="group").model_dump(mode="json"))
        for j in (mine, wide):
            env.store.update_job(j, status="failed")
        lp.job_log(mine).parent.mkdir(parents=True, exist_ok=True)
        lp.job_log(mine).write_text("{}\n")
        remove_source(lp, env.store, GONE, "t-remove")
        left = {f"job-{r['n']:06d}" for r in env.store.job_rows()}
        assert mine not in left and wide in left
        assert not lp.job_log(mine).exists()
    finally:
        env.close()


def test_the_same_file_added_again_is_selected_and_unchanged_decisions_apply(
    lp: ProjectPaths, labor_template: Path
) -> None:
    env, approved, _f = reviewed(lp)
    try:
        filename = lp.load_document(GONE).filename
        remove_source(lp, env.store, GONE, "t-remove")
    finally:
        env.close()
    src = labor_template / "sources" / filename
    ingest_files(lp, [src], emit=lambda _o: None)
    assert GONE in lp.list_slugs()
    from tests.export.helpers import labor_run

    labor_run(lp.root, "--to", "score2")
    env = Env(lp)
    try:
        assert graph.project_status(lp, None).removed == []
        assert [b for b in env.data.selection().block_ids if f"-{GONE}-" in b]
        by_id = {b.id: b for b in env.blocks(GONE)}
        assert by_id[approved].status.value == "approved"
    finally:
        env.close()


def test_labor_remove_needs_yes_and_prints_the_counts(lp: ProjectPaths) -> None:
    env, _a, _f = reviewed(lp)
    env.close()
    r = CliRunner().invoke(app, ["remove", str(lp.root), GONE])
    assert r.exit_code == 2, r.output
    assert "2 decisions" in r.output and "1 open flag" in r.output and "--yes" in r.output
    assert GONE in lp.list_slugs()
    r = CliRunner().invoke(app, ["remove", str(lp.root), GONE, "--yes"])
    assert r.exit_code == 0, r.output
    assert GONE not in lp.list_slugs()
    store = Store.open(lp)
    try:
        assert len(store.decisions(doc_id=GONE)) == 2
    finally:
        store.close()
    r = CliRunner().invoke(app, ["remove", str(lp.root), GONE, "--yes"])
    assert r.exit_code == 1 and "unknown" in r.output.lower()


def test_a_removed_manual_leaves_no_leftover_after_a_crash_mid_delete(lp: ProjectPaths) -> None:
    """A `.removed-*` directory left by a crash is ignored by list_slugs and deleted by the next
    removal."""
    own_sources(lp)
    stray = lp.docs / ".removed-old-abc"
    stray.mkdir()
    (stray / "document.json").write_text("{}")
    assert ".removed-old-abc" not in lp.list_slugs()
    env = Env(lp)
    try:
        remove_source(lp, env.store, GONE, "t-remove")
    finally:
        env.close()
    assert not stray.exists()


# -- review findings 3, 5, 7 ------------------------------------------------------------------


def test_a_legacy_selection_learns_the_known_manuals_on_removal(lp: ProjectPaths) -> None:
    """Finding 7: a selection saved before `known_docs` gets it with the removal, so the same
    manual added again arrives selected (design 08 section 10)."""
    env, _a, _f = reviewed(lp)
    try:
        raw = env.data.raw_selection()
        assert raw is not None
        legacy = raw.model_copy(update={"known_docs": None})
        with env.store.tx():
            aid = env.store.next_action_id()
            env.store.append_action(
                ActionKind.import_, "cli", payload={"what": "selection"}, action_id=aid
            )
            env.store.set_selection_json(legacy.model_dump_json(), aid)
        remove_source(lp, env.store, GONE, "t-remove")
        after = env.data.raw_selection()
        assert after is not None and after.known_docs == ["clean"]
    finally:
        env.close()


def test_a_failed_index_rebuild_still_finishes_the_removal(
    lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: the source file goes before the rebuild, and a rebuild error is left to the
    next figures run (which rebuilds the index) instead of a half-done removal."""
    import manuallabor.figures.pipeline as fp

    def boom(*_a: object, **_k: object) -> None:
        raise fp.FiguresError("index target missing")

    monkeypatch.setattr(fp, "rebuild_index", boom)
    env, _a, _f = reviewed(lp)
    try:
        filename = lp.load_document(GONE).filename
        out = remove_source(lp, env.store, GONE, "t-remove")
        assert out.removed and GONE not in lp.list_slugs()
        assert not lp.source(filename).exists()
    finally:
        env.close()


def test_removing_again_tidies_what_a_crash_left(lp: ProjectPaths) -> None:
    """Finding 3: a removed manual whose figures directory or source file survived a crash is
    tidied by the next removal request, which still answers not found."""
    env, _a, _f = reviewed(lp)
    try:
        filename = lp.load_document(GONE).filename
        remove_source(lp, env.store, GONE, "t-remove")
        (lp.figure_dir(GONE)).mkdir(parents=True)
        lp.source(filename).write_bytes(b"%PDF-1.4 left behind")
        with pytest.raises(NotFound):
            remove_source(lp, env.store, GONE, "t-remove-again")
        assert not lp.figure_dir(GONE).exists() and not lp.source(filename).exists()
    finally:
        env.close()


def test_a_job_queued_after_the_preview_still_refuses_inside_the_transaction(
    lp: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 5: the refusal is checked again inside the write transaction."""
    import manuallabor.state.sources as src
    from manuallabor.state.models import RunPlanIn

    env, _a, _f = reviewed(lp)
    try:
        real = src.removal

        def late_job(paths: ProjectPaths, store: Store, slug: str):  # type: ignore[no-untyped-def]
            p = real(paths, store, slug)
            store.add_job(
                kind="run", plan=RunPlanIn(to="group", docs=[slug]).model_dump(mode="json")
            )
            return p

        monkeypatch.setattr(src, "removal", late_job)
        with pytest.raises(Conflict):
            remove_source(lp, env.store, GONE, "t-remove")
        assert GONE in lp.list_slugs()
        assert not [a for a in env.store.iter_actions() if a.kind == ActionKind.remove_source]
    finally:
        env.close()


def test_tidying_never_touches_a_manual_that_is_live_again(lp: ProjectPaths) -> None:
    """Re-review: the tidy-up decides inside the worker lock. A manual re-added (same slug)
    between the 'not listed' check and the lock keeps its figures and source file."""
    from manuallabor.state.sources import _tidy_removed

    env, _a, _f = reviewed(lp)
    try:
        filename = lp.load_document(GONE).filename
        remove_source(lp, env.store, GONE, "t-remove")
    finally:
        env.close()
    from tests.conftest import FIXTURES

    ingest_files(lp, [FIXTURES / filename], emit=lambda _o: None)
    assert GONE in lp.list_slugs()
    lp.figure_dir(GONE).mkdir(parents=True, exist_ok=True)
    (lp.figure_dir(GONE) / "keep.txt").write_text("live")
    store = Store.open(lp)
    try:
        _tidy_removed(lp, store, GONE)  # as if the 'not listed' check had passed just before
    finally:
        store.close()
    assert (lp.figure_dir(GONE) / "keep.txt").exists() and lp.source(filename).exists()
