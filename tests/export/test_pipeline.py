"""E6/E7 (end to end), E14, E19-E21: the assemble/export pipeline and the `labor` commands."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from manuallabor.contracts.manifest import Manifest
from manuallabor.export import pipeline
from manuallabor.export.pipeline import (
    export_status,
    node_states,
    read_state,
    record_override,
    resolve_clock,
    run_assemble,
    run_export,
)
from manuallabor.export.types import ExportError, GateLocked, Problem
from manuallabor.export.validate import validate_zip
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp
from manuallabor.state.models import ActionKind, ReviewActionIn
from manuallabor.state.store import Store
from tests.export.helpers import CLOCK, CLOCK2, Exported, reviewer
from tests.subproc import run_bounded

LABOR = [sys.executable, "-m", "manuallabor"]


def labor(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, **(env or {})}
    return run_bounded(LABOR + list(args), timeout=600, env=e)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# -- E6: the gate, end to end ------------------------------------------------------------------


def test_e6_gate_refuses_then_unlocks(unreviewed: ProjectPaths) -> None:
    store = Store.open(unreviewed)
    try:
        st = export_status(unreviewed, store)
        assert st.unlocked is False and st.queued > 0 and st.blockers
        assert len(st.blockers) <= 20 and st.summary is None and st.zip_path is None
    finally:
        store.close()
    r = labor("export", str(unreviewed.root), "--now", CLOCK)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "queued" in r.stderr and "blocker: b-" in r.stderr
    assert not unreviewed.assembled.exists() and not list(unreviewed.export_dir.glob("*.zip"))
    r = labor("assemble", str(unreviewed.root), "--now", CLOCK)
    assert r.returncode == 2 and not unreviewed.assembled.exists()


def test_e6_an_open_flag_locks_an_otherwise_reviewed_project(work: ProjectPaths) -> None:
    store = Store.open(work)
    try:
        rev = reviewer(work, store)
        bid = store.decisions()[0].decision.block_id  # any reviewed block
        rev.act(
            ReviewActionIn(
                kind="flag",
                block_id=bid,
                flag={"category": "wrong_text", "note": "n"},  # type: ignore[arg-type]
                request_id="t-flag",
            )
        )
        st = export_status(work, store)
        assert st.open_flags == 1 and st.unlocked is False and bid in st.blockers
        with pytest.raises(GateLocked):
            run_assemble(work, store, clock=resolve_clock(CLOCK))
        assert not work.assembled.exists()
        rev.act(ReviewActionIn(kind="approve", block_id=bid, request_id="t-reapprove"))
        assert export_status(work, store).unlocked is True
    finally:
        store.close()


def test_labor_export_runs_end_to_end_and_validate_export_agrees(work: ProjectPaths) -> None:
    r = labor("export", str(work.root), "--now", CLOCK)
    assert r.returncode == 0, r.stdout + r.stderr
    zp = work.zip_path
    assert zp.is_file() and f"sha256 {sha(zp)}" in r.stdout
    v = labor("validate-export", str(zp))
    assert v.returncode == 0 and v.stdout.startswith("OK: ") and "articles" in v.stdout
    bad = work.export_dir / "bad.zip"
    bad.write_bytes(b"nope")
    v = labor("validate-export", str(bad))
    assert v.returncode == 1 and "Z1" in v.stdout and "INVALID" in v.stdout
    j = labor("export", str(work.root), "--now", CLOCK, "--json")
    assert j.returncode == 0 and json.loads(j.stdout)["zip_sha256"] == sha(zp)


# -- E7: overrides, end to end -----------------------------------------------------------------


def test_e7_override_exports_with_machine_text_and_expires_after_the_export(
    unreviewed: ProjectPaths,
) -> None:
    r = labor("export", str(unreviewed.root), "--now", CLOCK, "--override", "waived by test")
    assert r.returncode == 0, r.stdout + r.stderr
    with zipfile.ZipFile(unreviewed.zip_path) as zf:
        m = Manifest.model_validate_json(zf.read("manifest.json"))
        articles = {a.id: zf.read(a.path).decode() for a in m.articles}
    assert m.overrides and {o.reason for o in m.overrides} == {"waived by test"}
    assert m.review_stats.overrides == len(m.overrides)
    assert sum(1 for t in articles.values() if "overrides: 0" not in t) >= 1
    bodies = [t[t.index("\n---\n", 3) + 5 :] for t in articles.values()]
    assert all("override" not in b.lower() for b in bodies)  # no marker in the text
    assert validate_zip(unreviewed.zip_path) == []
    store = Store.open(unreviewed, readonly=True)
    try:
        kinds = [a.kind for a in store.iter_actions()]
        assert ActionKind.export_override in kinds and kinds[-1] == ActionKind.export_run
    finally:
        store.close()
    # an override older than the last export covers nothing new
    again = labor("export", str(unreviewed.root), "--now", CLOCK2)
    assert again.returncode == 2, again.stdout + again.stderr


def test_e7_targeted_override_and_unknown_targets(unreviewed: ProjectPaths) -> None:
    store = Store.open(unreviewed)
    try:
        st = export_status(unreviewed, store)
        first = st.blockers[0]
        with pytest.raises(InvalidOp):
            record_override(unreviewed, store, "r", target_id="b-nope-p001-01")
        with pytest.raises(InvalidOp):
            record_override(unreviewed, store, "r", flag_id="flag-000099")
        with pytest.raises(InvalidOp):
            record_override(unreviewed, store, "  ")
        a = record_override(unreviewed, store, "one block", target_id=first, request_id="rq-1")
        assert (
            record_override(unreviewed, store, "one block", target_id=first, request_id="rq-1") == a
        )
        st = export_status(unreviewed, store)
        assert [o.target_id for o in st.overrides] == [first] and first not in st.blockers
        assert st.unlocked is False and st.blockers  # the others still lock
    finally:
        store.close()
    r = labor("export", str(unreviewed.root), "--override", "x", "--target", "b-nope-p001-01")
    assert r.returncode == 2


# -- E14: determinism --------------------------------------------------------------------------


def test_e14_zip_is_byte_identical_across_processes_and_hash_seeds(
    approved_a: ProjectPaths, tmp_path: Path
) -> None:
    from tests.conftest import labor_copy

    outs = []
    for i, seed in enumerate(("1", "99")):
        p = ProjectPaths(labor_copy(approved_a.root, tmp_path / f"p{i}", db=True))
        r = labor("export", str(p.root), "--now", CLOCK, env={"PYTHONHASHSEED": seed})
        assert r.returncode == 0, r.stderr
        outs.append(p)
    z0, z1 = outs[0].zip_path, outs[1].zip_path
    assert sha(z0) == sha(z1)
    assert (outs[0].assembled / "manifest.json").read_bytes() == (
        outs[1].assembled / "manifest.json"
    ).read_bytes()
    assert (outs[0].assembled / "README.md").read_bytes() == (
        outs[1].assembled / "README.md"
    ).read_bytes()
    # a different clock changes only the `generated_at` lines
    p = outs[0]
    r = labor("export", str(p.root), "--now", CLOCK2, "--force")
    assert r.returncode == 0, r.stderr
    with zipfile.ZipFile(z1) as a, zipfile.ZipFile(p.zip_path) as b:
        assert a.namelist() == b.namelist()
        n_diff = 0
        for name in a.namelist():
            x, y = a.read(name), b.read(name)
            if x == y:
                continue
            assert (
                name.endswith((".md", ".json"))
                and not name.startswith("images/")
                or (name.endswith(".json"))
            )
            for lx, ly in zip(x.decode().split("\n"), y.decode().split("\n"), strict=True):
                if lx != ly:
                    n_diff += 1
                    stamped = ("2026-10-29T12:00:00Z" in lx, "2026-10-30T08:30:00Z" in ly)
                    assert stamped == (True, True), (name, lx, ly)  # only the timestamp moves
        assert n_diff > 0


# -- E19: stale inputs -------------------------------------------------------------------------


def test_e19_stale_inputs_refuse_and_node_states_say_so(work: ProjectPaths) -> None:
    store = Store.open(work)
    try:
        assert [s.state for s in node_states(work, store)] == ["missing", "missing"]
        run_export(work, store, clock=resolve_clock(CLOCK))
        assert [s.state for s in node_states(work, store)] == ["fresh", "fresh"]
        from manuallabor.state.data import ProjectData
        from manuallabor.state.models import SelectionOp
        from manuallabor.state.scope import ScopeService

        data = ProjectData(work, store)
        some = data.selection().block_ids[0]
        ScopeService(work, store, data).apply(
            SelectionOp(op="deselect", block_ids=[some], request_id="t-desel")
        )
        st = node_states(work, store)
        assert [s.state for s in st] == ["stale", "stale"] and "stale" in (st[0].reason or "")
        with pytest.raises(ExportError, match="stale"):
            run_assemble(work, store, clock=resolve_clock(CLOCK))
    finally:
        store.close()
    r = labor("export", str(work.root), "--now", CLOCK)
    assert r.returncode == 1 and "stale" in r.stderr


def test_e19_editing_blocks_json_makes_assemble_refuse(work: ProjectPaths) -> None:
    dp = work.doc("clean")
    blocks = json.loads(dp.blocks.read_text())
    blocks[0]["raw_text"] += " changed"
    dp.blocks.write_text(json.dumps(blocks))
    store = Store.open(work)
    try:
        with pytest.raises(ExportError, match="stale"):
            run_assemble(work, store, clock=resolve_clock(CLOCK))
    finally:
        store.close()
    assert labor("assemble", str(work.root)).returncode == 1


# -- E20: the fingerprint ----------------------------------------------------------------------


def test_e20_unchanged_inputs_skip_and_keep_the_bytes(work: ProjectPaths) -> None:
    store = Store.open(work)
    try:
        first = run_export(work, store, clock=resolve_clock(CLOCK))
        before = sha(work.zip_path)
        lines: list[dict[str, object]] = []
        second = run_export(work, store, clock=resolve_clock(CLOCK2), emit=lines.append)
        assert [(o["stage"], o["status"]) for o in lines] == [
            ("assemble", "skip"),
            ("export", "skip"),
        ]
        assert second.summary.zip_sha256 == first.summary.zip_sha256 == before == sha(work.zip_path)
        assert read_state(work).export is not None
        # a new approval changes what the export is made from
        rev = reviewer(work, store)
        bid = store.decisions()[0].decision.block_id
        rev.act(ReviewActionIn(kind="approve", block_id=bid, request_id="t-again"))
        lines.clear()
        third = run_export(work, store, clock=resolve_clock(CLOCK2), emit=lines.append)
        assert [o["status"] for o in lines] == ["built", "built"]
        assert third.summary.zip_sha256 != before and third.summary.generated_at.day == 30
        # --force rebuilds even though nothing changed
        lines.clear()
        run_export(work, store, clock=resolve_clock(CLOCK), emit=lines.append, force=True)
        assert [o["status"] for o in lines] == ["built", "built"]
    finally:
        store.close()


# -- E21: resume -------------------------------------------------------------------------------


def tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def test_e21_a_crash_after_assemble_resumes_to_the_same_export(
    work: ProjectPaths, exported_a: Exported
) -> None:
    store = Store.open(work)
    try:
        assert run_assemble(work, store, clock=resolve_clock(CLOCK)) == "built"
        (work.export_dir / "stray.zip.candidate").write_bytes(b"junk")
        stray = work.zip_path.with_name(work.zip_path.name + ".candidate")
        stray.write_bytes(b"half a zip")
        rec = run_export(work, store, clock=resolve_clock(CLOCK))
    finally:
        store.close()
    assert not stray.exists() and not list(work.export_dir.glob("*.rejected"))
    assert not list(work.export_dir.rglob("*.tmp"))
    assert tree(work.assembled) == tree(exported_a.paths.assembled)
    assert rec.summary.zip_sha256 == exported_a.sha


def test_e21_a_zip_that_does_not_validate_is_rejected_not_left(
    work: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline, "validate_zip", lambda _p: [Problem("Z9", "x", "forced for the test")]
    )
    store = Store.open(work)
    try:
        with pytest.raises(ExportError, match="does not validate"):
            run_export(work, store, clock=resolve_clock(CLOCK))
    finally:
        store.close()
    assert not work.zip_path.exists()
    assert work.zip_path.with_name(work.zip_path.name + ".rejected").is_file()
    assert read_state(work).export is None


def test_resolve_clock() -> None:
    assert resolve_clock("2026-10-29T12:00:00.987Z").isoformat() == "2026-10-29T12:00:00+00:00"
    with pytest.raises(ExportError):
        resolve_clock("yesterday")
    assert resolve_clock(None).microsecond == 0


# -- P3: the override cutoff lives in the action log (review fix) --------------------------------


def test_p3_the_cutoff_is_the_last_export_run_action_not_a_state_file(
    unreviewed: ProjectPaths,
) -> None:
    r = labor("export", str(unreviewed.root), "--now", CLOCK, "--override", "blanket")
    assert r.returncode == 0, r.stdout + r.stderr
    again = labor("export", str(unreviewed.root), "--now", CLOCK2)
    assert again.returncode == 2, again.stdout + again.stderr
    # a lost or deleted state file must not revive the spent override
    for p in unreviewed.export_dir.glob("*.json"):
        p.unlink()
    assert not unreviewed.export_state.exists()
    gone = labor("export", str(unreviewed.root), "--now", CLOCK2)
    assert gone.returncode == 2, gone.stdout + gone.stderr
    assert "blocker: b-" in gone.stderr
    store = Store.open(unreviewed, readonly=True)
    try:
        st = export_status(unreviewed, store)
        assert st.overrides == [] and st.blockers
        runs = store.actions_of((ActionKind.export_run,))
        assert len(runs) == 1
        ov = store.actions_of((ActionKind.export_override,))
        assert len(ov) == 1 and ov[0].id < runs[0].id
    finally:
        store.close()


def test_p3_a_corrupt_state_file_does_not_revive_a_spent_override(
    unreviewed: ProjectPaths,
) -> None:
    store = Store.open(unreviewed)
    try:
        record_override(unreviewed, store, "blanket", request_id="ov-c")
        run_export(unreviewed, store, clock=resolve_clock(CLOCK))
        unreviewed.export_state.write_text("{not json", encoding="utf-8")
        with pytest.raises(GateLocked):
            run_export(unreviewed, store, clock=resolve_clock(CLOCK2))
    finally:
        store.close()


def test_p3_without_a_store_the_export_refuses(work: ProjectPaths) -> None:
    work.db.unlink()
    for side in work.root.glob("project.db-*"):
        side.unlink()
    with pytest.raises(ExportError, match=r"project\.db"):
        run_export(work, None, clock=resolve_clock(CLOCK))
    assert not work.assembled.exists()


def test_after_an_override_export_the_nodes_are_fresh_not_stale(unreviewed: ProjectPaths) -> None:
    store = Store.open(unreviewed)
    try:
        record_override(unreviewed, store, "blanket", request_id="ov-f")
        run_export(unreviewed, store, clock=resolve_clock(CLOCK))
        assert [s.state for s in node_states(unreviewed, store)] == ["fresh", "fresh"]
        # ... but the spent override still covers nothing: a re-export is refused
        with pytest.raises(GateLocked):
            run_export(unreviewed, store, clock=resolve_clock(CLOCK2))
        # a new override is new input: the nodes go stale and the export rebuilds
        record_override(unreviewed, store, "again", request_id="ov-g")
        assert [s.state for s in node_states(unreviewed, store)] == ["stale", "stale"]
        lines: list[dict[str, object]] = []
        run_export(unreviewed, store, clock=resolve_clock(CLOCK), emit=lines.append)
        assert [o["status"] for o in lines if "stage" in o] == ["built", "built"]
        assert len(store.actions_of((ActionKind.export_run,))) == 2
        assert [s.state for s in node_states(unreviewed, store)] == ["fresh", "fresh"]
    finally:
        store.close()


def test_a_selected_block_missing_from_every_topic_is_refused_by_name(work: ProjectPaths) -> None:
    """The reviewer's mutation: groups.json loses a selected block from its topic, with the
    counts kept consistent. The export must refuse and name it, never call it `not_selected`."""
    from manuallabor.contracts.enums import BlockType
    from manuallabor.contracts.group import GroupsFile
    from manuallabor.contracts.io import read_json, write_json
    from manuallabor.export.assemble import assemble
    from manuallabor.export.load import load_inputs
    from manuallabor.grouping.pipeline import overlap
    from manuallabor.state.data import ProjectData
    from manuallabor.state.review import load_review_blocks

    dp = work.doc("clean")
    gf = read_json(dp.groups, GroupsFile)
    store = Store.open(work)
    try:
        selected = set(ProjectData(work, store).selection().block_ids)
        types = {b.id: b.type for b in load_review_blocks(work, store, "clean")}
    finally:
        store.close()
    topic = next(t for t in gf.topics if not t.is_unassigned and len(t.block_ids) >= 3)
    victim = next(b for b in topic.block_ids if b in selected and types[b] == BlockType.paragraph)
    topics = [
        t.model_copy(
            update={
                "block_ids": [b for b in t.block_ids if b != victim],
                "block_count": t.block_count - (victim in t.block_ids),
            }
        )
        for t in gf.topics
    ]
    gf = gf.model_copy(update={"topics": topics, "overlap": overlap(gf.structure, topics)})
    write_json(dp.groups, GroupsFile.model_validate(gf.model_dump(mode="json")))
    store = Store.open(work)
    try:
        with pytest.raises(ExportError, match=victim):
            assemble(load_inputs(work, store), resolve_clock(CLOCK))
    finally:
        store.close()
    # through the CLI the edited groups.json first makes the downstream nodes stale ...
    r = labor("export", str(work.root), "--now", CLOCK)
    assert r.returncode == 1 and "stale" in r.stderr, r.stdout + r.stderr
    # ... and once they are re-run on it, the export refuses with the block's id
    from tests.export.helpers import labor_run

    labor_run(work.root, "--to", "score2")
    r = labor("export", str(work.root), "--now", CLOCK)
    assert r.returncode == 1, r.stdout + r.stderr
    assert victim in r.stderr and "in no article" in r.stderr
    assert not work.zip_path.exists()
