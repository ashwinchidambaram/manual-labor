"""The read-only database URI is a quoted file URI (backend review 2 finding 2).

`file:{path}?mode=ro` left the path unquoted: `#` starts a fragment, `?` ends the path and `%xx`
is decoded, so SQLite opened another file and failed. With the re-parse guard failing closed, a
project under `~/Manuals #2/` refused every re-parse."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuallabor.jobs.executor import _reparse_guard, reparse_unknown
from manuallabor.project import ProjectPaths
from manuallabor.state.store import Store

NAMES = ["Manuals #2", "100% done", "what?x=1", "a b", "per%41cent"]


def _project(tmp_path: Path, name: str) -> ProjectPaths:
    root = tmp_path / name / "proj"
    root.mkdir(parents=True)
    paths = ProjectPaths(root)
    s = Store.open(paths)
    try:
        with s.tx():
            s.set_meta("probe", "written")
    finally:
        s.close()
    return paths


@pytest.mark.parametrize("name", NAMES)
def test_readonly_open_reads_the_project_database(tmp_path: Path, name: str) -> None:
    paths = _project(tmp_path, name)
    ro = Store.open(paths, readonly=True)
    try:
        assert ro.meta("probe") == "written"
    finally:
        ro.close()


@pytest.mark.parametrize("name", NAMES)
def test_reparse_guard_counts_decisions_under_such_a_path(tmp_path: Path, name: str) -> None:
    paths = _project(tmp_path, name)
    assert _reparse_guard(paths, "clean") is None  # zero decisions, counted


def test_an_unreadable_database_never_suggests_discarding_decisions() -> None:
    msg = reparse_unknown(OSError("unable to open database file"))
    assert "project.db" in msg and "unable to open database file" in msg
    assert "--discard-decisions" not in msg and "discard" not in msg.lower()
