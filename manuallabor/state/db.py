"""SQLite connection rules and migrations (design 07 section 2.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from manuallabor.state.errors import StateError
from manuallabor.state.migrations import MIGRATIONS

__all__ = ["StateError", "connect", "migrate"]


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        # a quoted file URI: `#`, `?` and `%` in a folder name are path characters, not URI
        # syntax (an unquoted `file:{path}` opened another file, review 2 finding 2)
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.isolation_level = None  # explicit BEGIN/COMMIT only
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> None:
    """Apply every missing migration, each in one transaction."""
    have = user_version(conn)
    if have > len(MIGRATIONS):
        raise StateError("project.db was written by a newer Manual Labor")
    for i in range(have, len(MIGRATIONS)):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split(MIGRATIONS[i]):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={i + 1}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def _split(script: str) -> list[str]:
    """Split a script into statements (triggers contain `;` inside BEGIN ... END)."""
    out: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        buf.append(line)
        joined = "\n".join(buf).strip()
        if joined and sqlite3.complete_statement(joined):
            out.append(joined)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out
