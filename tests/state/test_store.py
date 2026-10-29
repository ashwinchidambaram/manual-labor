"""S1-S3, S9, S10: the state database, idempotency, projections, locks."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from manuallabor.contracts.io import dump_json
from manuallabor.contracts.selection import Selection
from manuallabor.project import ProjectPaths
from manuallabor.state import db
from manuallabor.state.errors import LockHeld, StateError
from manuallabor.state.lock import ProjectLock
from manuallabor.state.migrations import MIGRATIONS
from manuallabor.state.models import ActionKind, SelectionOp
from manuallabor.state.store import Store

TABLES = {
    "meta", "blobs", "actions", "decisions", "flags", "proposals", "selection",
    "group_overrides", "attach_overrides", "figure_overrides", "review_cursor",
    "threshold_history", "jobs", "learning_snapshots",
}  # fmt: skip


def test_s1_fresh_db_has_every_table(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "p")
    paths.ensure_config()
    store = Store.open(paths)
    names = {r[0] for r in store.q("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= TABLES
    assert store.q1("PRAGMA user_version")[0] == len(MIGRATIONS)  # type: ignore[index]
    assert store.q1("PRAGMA journal_mode")[0] == "wal"  # type: ignore[index]
    store.close()
    Store.open(paths).close()  # a second open is a no-op


def test_s1_old_db_migrates_and_keeps_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "project.db"
    conn = db.connect(path)
    # an "old" database: only the first migration applied, with a row in it
    conn.execute("BEGIN IMMEDIATE")
    for stmt in db._split(MIGRATIONS[0]):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version=1")
    conn.execute("COMMIT")
    conn.execute("INSERT INTO meta(key, value) VALUES ('k', 'v')")
    conn.close()
    fake = [*MIGRATIONS, "CREATE TABLE extra_table (x INTEGER);"]
    monkeypatch.setattr(db, "MIGRATIONS", fake)
    conn = db.connect(path)
    db.migrate(conn)
    assert db.user_version(conn) == 2
    assert conn.execute("SELECT value FROM meta WHERE key='k'").fetchone()[0] == "v"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='extra_table'").fetchone()
    conn.close()


def test_s1_newer_db_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "project.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={len(MIGRATIONS) + 5}")
    conn.close()
    conn = db.connect(path)
    with pytest.raises(StateError, match="newer Manual Labor"):
        db.migrate(conn)
    conn.close()


def _append(store: Store, kind: ActionKind = ActionKind.cursor, **kw: object) -> int:
    with store.tx():
        return store.append_action(kind, "cli", **kw)  # type: ignore[arg-type]


def test_s2_append_only_and_monotonic(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "p")
    paths.ensure_config()
    store = Store.open(paths)
    ids = [_append(store, payload={"i": i}) for i in range(200)]
    assert ids == sorted(ids) and len(set(ids)) == 200
    for sql in ("UPDATE actions SET kind='x'", "DELETE FROM actions"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.x(sql)
    from manuallabor.contracts.enums import DecisionAction

    with store.tx():
        aid = store.next_action_id()
        store.append_action(ActionKind.skip, "verify", action_id=aid)
        store.add_decision(
            seq=store.next_decision_seq(), action_id=aid, block_id="b-doc-p001-01", doc_id="doc",
            action=DecisionAction.skip, score=None, threshold=0.85, signals=[], edited_text=None,
            flag_id=None, raw_sha256="0" * 64, shown_text_sha256="0" * 64, faith_passed=None,
            human_edit_diff=None, numbers_verified=False, provenance="baseline",
        )  # fmt: skip
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.x("UPDATE decisions SET action='x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.x("DELETE FROM decisions")
    # ids are never reused, even after a rolled-back transaction
    with pytest.raises(RuntimeError), store.tx():
        store.append_action(ActionKind.cursor, "cli")
        raise RuntimeError("boom")
    assert _append(store) > ids[-1]
    # flags only go open -> resolved, and are never deleted
    with store.tx():
        aid = store.next_action_id()
        from manuallabor.contracts.enums import FlagCategory

        store.append_action(ActionKind.flag, "verify", action_id=aid)
        f = store.add_flag(
            target_id="b-doc-p001-01", category=FlagCategory.wrong_text, note=None, action_id=aid
        )
        done = store.resolve_flag(f.id, "ok", aid)
    assert done.status.value == "resolved"
    with pytest.raises(sqlite3.DatabaseError):
        store.x("UPDATE flags SET status='open', resolved_at=NULL")
    with pytest.raises(sqlite3.DatabaseError):
        store.x("UPDATE flags SET note='x'")
    with pytest.raises(sqlite3.DatabaseError):
        store.x("DELETE FROM flags")
    store.close()


def test_s3_request_id_dedup(lp: ProjectPaths) -> None:
    from manuallabor.state.data import ProjectData
    from manuallabor.state.scope import ScopeService

    store = Store.open(lp)
    data = ProjectData(lp, store)
    scope = ScopeService(lp, store, data)
    ids = sorted(data.selection().block_ids)[:3]
    op = SelectionOp(op="deselect", block_ids=ids, request_id="req-1")
    first = scope.apply(op)
    n = store.count_actions()
    second = scope.apply(op)
    assert store.count_actions() == n
    assert first == second
    store.close()


def test_s9_projections_rebuild_byte_identical(lp: ProjectPaths) -> None:
    from manuallabor.state.data import ProjectData
    from manuallabor.state.models import RegroupIn
    from manuallabor.state.scope import ScopeService

    store = Store.open(lp)
    data = ProjectData(lp, store)
    scope = ScopeService(lp, store, data)
    sel = sorted(data.selection().block_ids)
    scope.apply(SelectionOp(op="deselect", block_ids=sel[:5], request_id="a"))
    gf = data.groups("clean")
    assert gf is not None
    topics = [t for t in gf.topics if not t.is_unassigned]
    mover = topics[0].block_ids[0]
    scope.regroup(
        RegroupIn(
            doc_id="clean",
            kind="move",
            block_id=mover,
            to_topic_slug=topics[1].slug,
            request_id="b",
        )
    )
    scope.regroup(
        RegroupIn(
            doc_id="clean",
            kind="rename",
            topic_slug=topics[1].slug,
            title="Renamed",
            request_id="c",
        )
    )
    want = {
        "sel": lp.selection.read_bytes(),
        "ov": lp.doc("clean").group_overrides.read_bytes(),
    }
    saved = Selection.model_validate_json(store.get_selection_json() or "")
    assert lp.selection.read_text() == dump_json(saved)
    assert [o["kind"] for o in json.loads(want["ov"])] == ["move", "rename"]
    store.close()
    lp.selection.unlink()
    lp.doc("clean").group_overrides.unlink()
    Store.open(lp).close()  # reconcile
    assert lp.selection.read_bytes() == want["sel"]
    assert lp.doc("clean").group_overrides.read_bytes() == want["ov"]


def test_s9_legacy_files_are_imported_once(lp: ProjectPaths) -> None:
    from manuallabor.grouping.selection import default_selection, save_selection

    sel = default_selection(lp)
    sel = sel.model_copy(update={"block_ids": sel.block_ids[:10]})
    save_selection(lp, sel)
    ov = [{"seq": 1, "kind": "rename", "topic_slug": "x-y", "title": "T"}]
    lp.doc("clean").group_overrides.write_text(json.dumps(ov))
    store = Store.open(lp)
    kinds = [a.kind for a in store.iter_actions()]
    assert kinds.count(ActionKind.import_) == 2
    n = store.count_actions()
    store.close()
    store = Store.open(lp)
    assert store.count_actions() == n  # not imported twice
    assert (
        Selection.model_validate_json(store.get_selection_json() or "").block_ids == sel.block_ids
    )
    store.close()


HOLDER = (
    "import sys, time\n"
    "from manuallabor.state.lock import ProjectLock\n"
    "lk = ProjectLock(sys.argv[1], cmd='holder'); lk.acquire(); print('held', flush=True)\n"
    "time.sleep(60)\n"
)


def _holder(path: Path) -> subprocess.Popen[str]:
    p = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path)], stdout=subprocess.PIPE, text=True
    )
    assert p.stdout is not None and p.stdout.readline().strip() == "held"
    return p


def test_s10_second_writer_exits_3_naming_the_pid(lp: ProjectPaths) -> None:
    holder = _holder(lp.lock)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "manuallabor", "run", str(lp.root), "--mock"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert r.returncode == 3
        assert str(holder.pid) in r.stderr
        with pytest.raises(LockHeld) as ei:
            ProjectLock(lp.lock).acquire()
        assert ei.value.owner["pid"] == holder.pid
    finally:
        holder.kill()
        holder.wait()
    lk = ProjectLock(lp.lock)
    lk.acquire()  # the kernel released it when the holder died
    lk.release()


def test_s10_orphan_worker_lock_blocks_run(lp: ProjectPaths) -> None:
    holder = _holder(lp.worker_lock)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "manuallabor", "run", str(lp.root), "--mock"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert r.returncode == 3
        assert str(holder.pid) in r.stderr
        # the project lock was released again
        lk = ProjectLock(lp.lock)
        lk.acquire()
        lk.release()
    finally:
        holder.kill()
        holder.wait()
    time.sleep(0)
