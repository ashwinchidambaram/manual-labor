"""Fault-injection hook for the kill-and-resume tests (design 07 section 8).

`fault(point)` SIGKILLs the current process when `MANUALLABOR_FAULT` names exactly this
point. It is compiled in permanently and is a no-op without the environment variable.
Points: `action.after_insert`, `action.after_commit`, `node.after:<node>:<slug>` (after the
unit finished, before stages.json records it), `llm.after_calls:<n>` (all calls) and
`llm.after_calls:<node>:<n>` (calls made while that node runs), `score.after_history`,
`score.after_scores`.

`delay(point)` sleeps `MANUALLABOR_DELAY=<point>=<seconds>` at a point (the cancel tests need a
unit that is reliably still running)."""

from __future__ import annotations

import os
import signal
import time


def fault(point: str) -> None:
    if os.environ.get("MANUALLABOR_FAULT") == point:
        os.kill(os.getpid(), signal.SIGKILL)


def delay(point: str) -> None:
    spec = os.environ.get("MANUALLABOR_DELAY")
    if spec and "=" in spec:
        name, _, seconds = spec.rpartition("=")
        if name == point:
            time.sleep(float(seconds))
