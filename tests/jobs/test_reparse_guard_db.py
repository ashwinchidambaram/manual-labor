"""The re-parse guard fails closed when project.db cannot be read (code review F7).

A database that does not open (corrupt bytes, a newer schema) used to count as "no decisions",
so the one guard that protects a reviewer's work let a re-parse through and orphaned every
decision. Unknown must refuse, naming the database error, and must not suggest
`--discard-decisions` (review 2 finding 2), which still overrides when given."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable

import pytest

from manuallabor.jobs.executor import make_plan, run_node
from manuallabor.project import ProjectPaths
from manuallabor.state.models import ReviewActionIn
from tests.state.helpers import Env


def _decide(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        page = env.review.queue(None, None, "scanned", 5, 0)
        env.review.act(
            ReviewActionIn(kind="approve", block_id=page.items[0].block_id, request_id="x")
        )
    finally:
        env.close()


def _corrupt(lp: ProjectPaths) -> None:
    for p in lp.root.glob("project.db-*"):
        p.unlink()
    lp.db.write_bytes(b"this is not an sqlite database" * 100)


def _newer_schema(lp: ProjectPaths) -> None:
    conn = sqlite3.connect(lp.db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()


BREAKERS: dict[str, Callable[[ProjectPaths], None]] = {
    "corrupt": _corrupt,
    "newer_schema": _newer_schema,
}


@pytest.mark.parametrize("breaker", sorted(BREAKERS))
def test_make_plan_refuses_a_reparse_when_decisions_cannot_be_counted(
    lp: ProjectPaths, breaker: str
) -> None:
    _decide(lp)
    BREAKERS[breaker](lp)
    cfg = lp.load_config()
    lp.doc("scanned").state.unlink()
    plan = make_plan(lp, cfg)
    assert plan.units == [], plan.units
    assert [s for s, _ in plan.refused] == ["scanned"]
    msg = plan.refused[0][1]
    assert "project.db" in msg and "--discard-decisions" not in msg, msg  # never suggested
    # the explicit override still works
    plan = make_plan(lp, cfg, allow_reparse=True)
    assert plan.units[0] == ("parse", "scanned") and not plan.refused


def test_labor_parse_refuses_when_decisions_cannot_be_counted(lp: ProjectPaths) -> None:
    _decide(lp)
    _corrupt(lp)
    blocks = lp.doc("scanned").blocks
    before = hashlib.sha256(blocks.read_bytes()).hexdigest()
    lines: list[dict[str, object]] = []
    failed = run_node(lp, "parse", only="scanned", force=True, emit=lines.append)
    assert failed == ["scanned"]
    err = [o for o in lines if o.get("status") == "error" and o.get("doc") == "scanned"]
    assert err and "project.db" in str(err[0]["detail"]), lines
    assert hashlib.sha256(blocks.read_bytes()).hexdigest() == before  # nothing re-parsed


def test_a_project_without_a_database_is_not_refused(lp: ProjectPaths) -> None:
    assert not lp.db.exists()
    cfg = lp.load_config()
    lp.doc("scanned").state.unlink()
    plan = make_plan(lp, cfg)
    assert plan.units and plan.units[0] == ("parse", "scanned") and not plan.refused
