"""The only code that touches project.db (design 07 section 2).

One writer process per project (the caller holds the ProjectLock). Every user action is one
`BEGIN IMMEDIATE ... COMMIT` transaction; projections (files stages read) are written after the
commit through `after_commit` callbacks and healed by `reconcile` on the next open."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from manuallabor import faults
from manuallabor.contracts._base import _fmt_utc, _parse_utc
from manuallabor.contracts.block import DiffOp, Signal
from manuallabor.contracts.decision import Decision
from manuallabor.contracts.enums import DecisionAction, FlagCategory, FlagStatus
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.io import canonical_json
from manuallabor.project import ProjectPaths
from manuallabor.providers.base import Clock, utc_now
from manuallabor.state import db
from manuallabor.state.migrations import MIGRATIONS
from manuallabor.state.models import (
    ActionKind,
    ActionRecord,
    Cursor,
    DecisionRecord,
    SnapshotInfo,
)

__all__ = ["Store", "fmt_ts", "parse_ts", "sha_text"]


def fmt_ts(dt: datetime) -> str:
    return str(_fmt_utc(dt))


def parse_ts(s: str) -> datetime:
    out = _parse_utc(s)
    assert isinstance(out, datetime)
    return out


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _j(obj: Any) -> str:
    return canonical_json(obj).decode("utf-8")


class Store:
    def __init__(
        self, paths: ProjectPaths, conn: sqlite3.Connection, clock: Clock, *, writer: bool
    ) -> None:
        self.paths = paths
        self.conn = conn
        self.clock = clock
        self.writer = writer
        self._lock = threading.RLock()
        self._depth = 0
        self._after: list[Callable[[], object]] = []
        self._wrote_action = False

    # -- lifecycle ------------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        paths: ProjectPaths,
        *,
        clock: Clock = utc_now,
        readonly: bool = False,
        reconcile: bool = True,
    ) -> Store:
        if readonly:
            conn = db.connect(paths.db, readonly=True)
            if db.user_version(conn) > len(MIGRATIONS):
                conn.close()
                raise db.StateError("project.db was written by a newer Manual Labor")
            return cls(paths, conn, clock, writer=False)
        conn = db.connect(paths.db)
        try:
            db.migrate(conn)
        except BaseException:
            conn.close()
            raise
        store = cls(paths, conn, clock, writer=True)
        if store.meta("project_uuid") is None:
            import uuid

            with store.tx():
                store.set_meta("project_uuid", uuid.uuid4().hex)
                store.set_meta("created_at", fmt_ts(clock()))
        if reconcile:
            from manuallabor.state.projections import reconcile as do_reconcile

            do_reconcile(store, paths)
        return store

    def close(self) -> None:
        with self._lock:
            try:
                if self.writer:
                    self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self.conn.close()

    def now(self) -> str:
        return fmt_ts(self.clock())

    # -- transactions ---------------------------------------------------------------------

    @contextmanager
    def tx(self) -> Iterator[Store]:
        """One user action = one transaction. Nested use joins the outer one."""
        with self._lock:
            if self._depth > 0:
                self._depth += 1
                try:
                    yield self
                finally:
                    self._depth -= 1
                return
            self.conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            self._after = []
            self._wrote_action = False
            try:
                yield self
                if self._wrote_action:
                    faults.fault("action.after_insert")
                self.conn.execute("COMMIT")
            except BaseException:
                self._depth = 0
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
            self._depth = 0
            callbacks, self._after = self._after, []
            if self._wrote_action:
                faults.fault("action.after_commit")
            for fn in callbacks:
                fn()

    def after_commit(self, fn: Callable[[], object]) -> None:
        if self._depth == 0:
            fn()
        else:
            self._after.append(fn)

    # -- generic --------------------------------------------------------------------------

    def q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def q1(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self.conn.execute(sql, args).fetchone()
            return row

    def x(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, args)

    def meta(self, key: str) -> str | None:
        r = self.q1("SELECT value FROM meta WHERE key=?", (key,))
        return None if r is None else str(r[0])

    def set_meta(self, key: str, value: str) -> None:
        self.x("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def integrity_ok(self) -> bool:
        r = self.q1("PRAGMA integrity_check")
        return r is not None and str(r[0]) == "ok"

    # -- blobs ----------------------------------------------------------------------------

    def put_blob(self, body: str) -> str:
        sha = sha_text(body)
        self.x("INSERT OR IGNORE INTO blobs(sha256, body) VALUES (?, ?)", (sha, body))
        return sha

    def get_blob(self, sha: str | None) -> str | None:
        if sha is None:
            return None
        r = self.q1("SELECT body FROM blobs WHERE sha256=?", (sha,))
        return None if r is None else str(r[0])

    # -- actions --------------------------------------------------------------------------

    def next_action_id(self) -> int:
        r = self.q1("SELECT seq FROM sqlite_sequence WHERE name='actions'")
        return 1 if r is None else int(r[0]) + 1

    def next_decision_seq(self) -> int:
        r = self.q1("SELECT seq FROM sqlite_sequence WHERE name='decisions'")
        return 1 if r is None else int(r[0]) + 1

    def action_by_request(self, request_id: str | None) -> ActionRecord | None:
        if request_id is None:
            return None
        r = self.q1("SELECT * FROM actions WHERE request_id=?", (request_id,))
        return None if r is None else _action(r)

    def append_action(
        self,
        kind: ActionKind,
        screen: str,
        *,
        target_id: str | None = None,
        doc_id: str | None = None,
        payload: dict[str, Any] | None = None,
        example: dict[str, Any] | None = None,
        before: str | None = None,
        after: str | None = None,
        provenance: str | None = None,
        request_id: str | None = None,
        action_id: int | None = None,
    ) -> int:
        """Insert one action row (inside a `tx`). `action_id` lets the caller know the id
        before the insert (it is part of the outcome stored in the payload)."""
        if self._depth == 0:
            raise RuntimeError("append_action outside a transaction")
        before_ref = self.put_blob(before) if before is not None else None
        after_ref = self.put_blob(after) if after is not None else None
        aid = action_id if action_id is not None else self.next_action_id()
        self.x(
            "INSERT INTO actions(id, ts, screen, kind, target_id, doc_id, payload, example, "
            "before_ref, after_ref, learning_provenance, request_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                self.now(),
                screen,
                kind.value,
                target_id,
                doc_id,
                _j(payload or {}),
                None if example is None else _j(example),
                before_ref,
                after_ref,
                provenance,
                request_id,
            ),
        )
        self._wrote_action = True
        return aid

    def iter_actions(self) -> Iterator[ActionRecord]:
        for r in self.q("SELECT * FROM actions ORDER BY id"):
            yield _action(r)

    def get_action(self, action_id: int) -> ActionRecord | None:
        r = self.q1("SELECT * FROM actions WHERE id=?", (action_id,))
        return None if r is None else _action(r)

    def max_action_id(self) -> int:
        r = self.q1("SELECT MAX(id) FROM actions")
        return 0 if r is None or r[0] is None else int(r[0])

    def count_actions(self) -> int:
        return int(self.q1("SELECT COUNT(*) FROM actions")[0])  # type: ignore[index]

    # -- decisions ------------------------------------------------------------------------

    def add_decision(
        self,
        *,
        seq: int,
        action_id: int,
        block_id: str,
        doc_id: str,
        action: DecisionAction,
        score: float | None,
        threshold: float,
        signals: list[Signal],
        edited_text: str | None,
        flag_id: str | None,
        raw_sha256: str,
        shown_text_sha256: str,
        faith_passed: bool | None,
        human_edit_diff: list[DiffOp] | None,
        numbers_verified: bool,
        provenance: str,
        source: str = "human",
    ) -> None:
        self.x(
            "INSERT INTO decisions(seq, action_id, block_id, doc_id, action, score, threshold, "
            "signals, edited_text, flag_id, ts, raw_sha256, shown_text_sha256, faith_passed, "
            "human_edit_diff, numbers_verified, learning_provenance, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                seq,
                action_id,
                block_id,
                doc_id,
                action.value,
                score,
                threshold,
                _j([s.model_dump(mode="json") for s in signals]),
                edited_text,
                flag_id,
                self.now(),
                raw_sha256,
                shown_text_sha256,
                None if faith_passed is None else int(faith_passed),
                None
                if human_edit_diff is None
                else _j([d.model_dump(mode="json") for d in human_edit_diff]),
                int(numbers_verified),
                provenance,
                source,
            ),
        )

    def decisions(
        self, block_id: str | None = None, doc_id: str | None = None
    ) -> list[DecisionRecord]:
        sql = "SELECT * FROM decisions"
        args: list[Any] = []
        where = []
        if block_id is not None:
            where.append("block_id=?")
            args.append(block_id)
        if doc_id is not None:
            where.append("doc_id=?")
            args.append(doc_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY seq"
        return [_decision(r) for r in self.q(sql, tuple(args))]

    def decisions_by_provenance(self) -> dict[str, list[DecisionRecord]]:
        """Module 10's A/B hook: decisions grouped by the learning provenance they saw."""
        out: dict[str, list[DecisionRecord]] = {}
        for d in self.decisions():
            out.setdefault(d.learning_provenance, []).append(d)
        return out

    def numbers_verified_blocks(self, current_raw: dict[str, str] | None = None) -> list[str]:
        """Block ids whose latest effective decision is an approve/edit with numbers_verified.
        `current_raw` (block id -> raw_text) drops decisions made on other raw text."""
        latest: dict[str, DecisionRecord] = {}
        for d in self.decisions():
            if d.decision.action == DecisionAction.skip:
                continue
            if current_raw is not None:
                raw = current_raw.get(d.decision.block_id)
                if raw is None or sha_text(raw) != d.raw_sha256:
                    continue
            latest[d.decision.block_id] = d
        return sorted(
            b
            for b, d in latest.items()
            if d.numbers_verified
            and d.decision.action in (DecisionAction.approve, DecisionAction.edit)
        )

    # -- flags ----------------------------------------------------------------------------

    def add_flag(
        self, *, target_id: str, category: FlagCategory, note: str | None, action_id: int
    ) -> Flag:
        ts = self.now()
        cur = self.x(
            "INSERT INTO flags(target_id, category, note, status, created_at, created_action_id) "
            "VALUES (?,?,?,?,?,?)",
            (target_id, category.value, note, FlagStatus.open.value, ts, action_id),
        )
        f = self.get_flag(f"flag-{cur.lastrowid:06d}")
        assert f is not None
        return f

    def get_flag(self, flag_id: str) -> Flag | None:
        try:
            n = int(flag_id.split("-", 1)[1])
        except (IndexError, ValueError):
            return None
        r = self.q1("SELECT * FROM flags WHERE n=?", (n,))
        return None if r is None else _flag(r)

    def flags(self, status: FlagStatus | None = None) -> list[Flag]:
        if status is None:
            rows = self.q("SELECT * FROM flags ORDER BY n")
        else:
            rows = self.q("SELECT * FROM flags WHERE status=? ORDER BY n", (status.value,))
        return [_flag(r) for r in rows]

    def open_flags_for(self, target_id: str) -> list[Flag]:
        rows = self.q(
            "SELECT * FROM flags WHERE target_id=? AND status='open' ORDER BY n", (target_id,)
        )
        return [_flag(r) for r in rows]

    def open_flag_count(self) -> int:
        return int(self.q1("SELECT COUNT(*) FROM flags WHERE status='open'")[0])  # type: ignore[index]

    def resolve_flag(self, flag_id: str, resolution: str, action_id: int) -> Flag:
        n = int(flag_id.split("-", 1)[1])
        self.x(
            "UPDATE flags SET status='resolved', resolved_at=?, resolution=?, "
            "resolved_action_id=? WHERE n=? AND status='open'",
            (self.now(), resolution, action_id, n),
        )
        f = self.get_flag(flag_id)
        assert f is not None
        return f

    # -- selection / overrides / cursor ---------------------------------------------------

    def get_selection_json(self) -> str | None:
        r = self.q1("SELECT body FROM selection WHERE id=1")
        return None if r is None else str(r[0])

    def set_selection_json(self, body: str, action_id: int) -> None:
        self.x(
            "INSERT OR REPLACE INTO selection(id, body, action_id) VALUES (1, ?, ?)",
            (body, action_id),
        )

    def add_override(self, table: str, seq: int, doc_id: str, body: str, action_id: int) -> None:
        assert table in ("group_overrides", "attach_overrides")
        self.x(
            f"INSERT INTO {table}(seq, doc_id, body, action_id) VALUES (?,?,?,?)",  # noqa: S608
            (seq, doc_id, body, action_id),
        )

    def next_override_seq(self, table: str) -> int:
        r = self.q1("SELECT seq FROM sqlite_sequence WHERE name=?", (table,))
        return 1 if r is None else int(r[0]) + 1

    def overrides(self, table: str, doc_id: str | None = None) -> list[tuple[int, str, str]]:
        """(seq, doc_id, body json) rows by seq."""
        assert table in ("group_overrides", "attach_overrides")
        if doc_id is None:
            rows = self.q(f"SELECT seq, doc_id, body FROM {table} ORDER BY seq")  # noqa: S608
        else:
            rows = self.q(
                f"SELECT seq, doc_id, body FROM {table} WHERE doc_id=? ORDER BY seq",  # noqa: S608
                (doc_id,),
            )
        return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    def add_figure_override(
        self, seq: int, doc_id: str, figure_id: str, bbox: list[float], action_id: int
    ) -> None:
        self.x(
            "INSERT INTO figure_overrides(seq, doc_id, figure_id, bbox, action_id) "
            "VALUES (?,?,?,?,?)",
            (seq, doc_id, figure_id, _j(bbox), action_id),
        )

    def next_figure_override_seq(self) -> int:
        r = self.q1("SELECT seq FROM sqlite_sequence WHERE name='figure_overrides'")
        return 1 if r is None else int(r[0]) + 1

    def figure_overrides(
        self, doc_id: str | None = None
    ) -> list[tuple[int, str, str, list[float]]]:
        """(seq, doc_id, figure_id, bbox) rows by seq (all history)."""
        if doc_id is None:
            rows = self.q("SELECT * FROM figure_overrides ORDER BY seq")
        else:
            rows = self.q("SELECT * FROM figure_overrides WHERE doc_id=? ORDER BY seq", (doc_id,))
        return [
            (int(r["seq"]), str(r["doc_id"]), str(r["figure_id"]), json.loads(r["bbox"]))
            for r in rows
        ]

    def get_cursor(self) -> Cursor | None:
        r = self.q1("SELECT body FROM review_cursor WHERE id=1")
        return None if r is None else Cursor.model_validate_json(str(r[0]))

    def set_cursor(self, c: Cursor, action_id: int) -> None:
        self.x(
            "INSERT OR REPLACE INTO review_cursor(id, body, action_id) VALUES (1, ?, ?)",
            (_j(c.model_dump(mode="json")), action_id),
        )

    def add_threshold_history(
        self, kind: str, old: float | None, new: float, reason: str, action_id: int
    ) -> None:
        self.x(
            "INSERT INTO threshold_history(ts, kind, old, new, reason, action_id) "
            "VALUES (?,?,?,?,?,?)",
            (self.now(), kind, old, new, reason, action_id),
        )

    # -- learning snapshots ---------------------------------------------------------------

    def add_snapshot(
        self,
        *,
        id_: str,
        parent: str | None,
        origin: str,
        first: int | None,
        last: int | None,
        counts: dict[str, int],
        path: str,
    ) -> None:
        self.x(
            "INSERT INTO learning_snapshots(id, created_at, parent, origin, source_first_action, "
            "source_last_action, counts, path, active) VALUES (?,?,?,?,?,?,?,?,0)",
            (id_, self.now(), parent, origin, first, last, _j(counts), path),
        )

    def snapshots(self) -> list[SnapshotInfo]:
        return [_snapshot(r) for r in self.q("SELECT * FROM learning_snapshots ORDER BY id")]

    def get_snapshot(self, id_: str) -> SnapshotInfo | None:
        r = self.q1("SELECT * FROM learning_snapshots WHERE id=?", (id_,))
        return None if r is None else _snapshot(r)

    def active_snapshot(self) -> SnapshotInfo | None:
        r = self.q1("SELECT * FROM learning_snapshots WHERE active=1")
        return None if r is None else _snapshot(r)

    def set_active_snapshot(self, id_: str | None) -> None:
        self.x("UPDATE learning_snapshots SET active=0 WHERE active=1")
        if id_ is not None:
            self.x("UPDATE learning_snapshots SET active=1 WHERE id=?", (id_,))

    def snapshot_origin(self, id_: str) -> str | None:
        r = self.q1("SELECT origin FROM learning_snapshots WHERE id=?", (id_,))
        return None if r is None else str(r[0])

    def next_snapshot_id(self) -> str:
        r = self.q1("SELECT MAX(id) FROM learning_snapshots WHERE origin <> 'global'")
        n = 0 if r is None or r[0] is None else int(r[0])
        return f"{n + 1:03d}"

    # -- jobs -----------------------------------------------------------------------------

    def add_job(
        self,
        *,
        kind: str,
        plan: dict[str, Any],
        units_total: int = 0,
        resumed_from: str | None = None,
    ) -> str:
        cur = self.x(
            "INSERT INTO jobs(kind, plan, status, units_total, created_at, resumed_from) "
            "VALUES (?,?,?,?,?,?)",
            (kind, _j(plan), "queued", units_total, self.now(), resumed_from),
        )
        return f"job-{cur.lastrowid:06d}"

    def job_row(self, job_id: str) -> sqlite3.Row | None:
        try:
            n = int(job_id.split("-", 1)[1])
        except (IndexError, ValueError):
            return None
        return self.q1("SELECT * FROM jobs WHERE n=?", (n,))

    def job_rows(self, statuses: set[str] | None = None) -> list[sqlite3.Row]:
        rows = self.q("SELECT * FROM jobs ORDER BY n")
        if statuses is None:
            return rows
        return [r for r in rows if r["status"] in statuses]

    def update_job(self, job_id: str, **fields: Any) -> None:
        n = int(job_id.split("-", 1)[1])
        allowed = {
            "status", "progress", "units_done", "units_total", "node", "doc", "message",
            "started_at", "finished_at", "pid", "log_path", "exit_code", "error",
            "cancel_requested", "plan",
        }  # fmt: skip
        sets = []
        args: list[Any] = []
        for k, v in fields.items():
            assert k in allowed, k
            sets.append(f"{k}=?")
            args.append(_j(v) if k == "plan" else v)
        args.append(n)
        self.x(f"UPDATE jobs SET {', '.join(sets)} WHERE n=?", tuple(args))  # noqa: S608


# -- row converters ---------------------------------------------------------------------------


def _action(r: sqlite3.Row) -> ActionRecord:
    return ActionRecord(
        id=r["id"],
        ts=parse_ts(r["ts"]),
        screen=r["screen"],
        kind=ActionKind(r["kind"]),
        target_id=r["target_id"],
        doc_id=r["doc_id"],
        payload=json.loads(r["payload"]),
        example=None if r["example"] is None else json.loads(r["example"]),
        before_ref=r["before_ref"],
        after_ref=r["after_ref"],
        learning_provenance=r["learning_provenance"],
        request_id=r["request_id"],
    )


def _decision(r: sqlite3.Row) -> DecisionRecord:
    d = Decision(
        seq=r["seq"],
        block_id=r["block_id"],
        action=DecisionAction(r["action"]),
        score=r["score"],
        threshold=r["threshold"],
        signals=[Signal.model_validate(s) for s in json.loads(r["signals"])],
        edited_text=r["edited_text"],
        flag_id=r["flag_id"],
        timestamp=parse_ts(r["ts"]),
    )
    diff = r["human_edit_diff"]
    return DecisionRecord(
        decision=d,
        action_id=r["action_id"],
        doc_id=r["doc_id"],
        raw_sha256=r["raw_sha256"],
        shown_text_sha256=r["shown_text_sha256"],
        faith_passed=None if r["faith_passed"] is None else bool(r["faith_passed"]),
        human_edit_diff=None
        if diff is None
        else [DiffOp.model_validate(x) for x in json.loads(diff)],
        numbers_verified=bool(r["numbers_verified"]),
        learning_provenance=r["learning_provenance"],
        source=r["source"],
    )


def _flag(r: sqlite3.Row) -> Flag:
    return Flag(
        id=f"flag-{r['n']:06d}",
        target_id=r["target_id"],
        category=FlagCategory(r["category"]),
        note=r["note"],
        status=FlagStatus(r["status"]),
        created_at=parse_ts(r["created_at"]),
        resolved_at=None if r["resolved_at"] is None else parse_ts(r["resolved_at"]),
        resolution=r["resolution"],
    )


def _snapshot(r: sqlite3.Row) -> SnapshotInfo:
    return SnapshotInfo(
        id=r["id"],
        created_at=parse_ts(r["created_at"]),
        parent=r["parent"],
        origin=r["origin"],
        source_first_action=r["source_first_action"],
        source_last_action=r["source_last_action"],
        counts=json.loads(r["counts"]),
        active=bool(r["active"]),
    )
