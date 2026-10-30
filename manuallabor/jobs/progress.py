"""Inner progress of one stage unit (design 07 section 4.1): how far a stage is through the pages,
blocks or topics of one document, for the jobs bar.

A stage calls `report(doc, done, total, unit)` where it already counts its work; without a
reporter (the CLI, tests, a direct call) that is a no-op. The job worker installs a reporter that
writes a `step` event into the job log. Only real counts are reported: a stage with no countable
inner work reports nothing, and the UI then says it has no estimate."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

__all__ = ["StepUnit", "Reporter", "report", "set_reporter"]

StepUnit = Literal["page", "block", "topic"]
Reporter = Callable[[str, int, int, StepUnit], None]

_lock = threading.Lock()
_reporter: Reporter | None = None


def set_reporter(fn: Reporter | None) -> Reporter | None:
    """Install `fn` (None removes it); returns the previous reporter."""
    global _reporter
    with _lock:
        prev, _reporter = _reporter, fn
    return prev


def report(doc: str, done: int, total: int, unit: StepUnit) -> None:
    """`done` of `total` `unit`s of `doc` are finished (or, for `page`, reached). Ignored when no
    reporter is installed or the counts are not a real fraction."""
    fn = _reporter
    if fn is None or total <= 0 or not 0 <= done <= total:
        return
    fn(doc, done, total, unit)
