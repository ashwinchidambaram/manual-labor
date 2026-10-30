"""Run a `labor` (or any) child process from a test with a hard time limit.

A child that hangs must fail its test, not stall the whole run: the child gets its own session,
and on timeout the whole process group is killed (the spawned render/OCR workers included, which
`subprocess.run(timeout=...)` would leave running), then `pytest.fail` reports the output so far.
Every test that runs a pipeline stage in a child process goes through here (CLAUDE.md)."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

# a `labor run --mock` over two Docling-parsed PDFs takes a few minutes on the reference machine,
# longer under a full parallel gate; fifteen minutes is far beyond any healthy run
LABOR_TIMEOUT = 900.0


def run_bounded(
    args: Sequence[str], *, timeout: float = LABOR_TIMEOUT, **kw: Any
) -> subprocess.CompletedProcess[str]:
    """`subprocess.run(args, capture_output=True, text=True, **kw)` that kills the child's whole
    process group and fails the test after `timeout` seconds."""
    check = bool(kw.pop("check", False))
    kw.pop("capture_output", None)  # always captured (unless stdout/stderr are given)
    kw.setdefault("text", True)
    with subprocess.Popen(  # noqa: S603
        list(args),
        stdout=kw.pop("stdout", subprocess.PIPE),
        stderr=kw.pop("stderr", subprocess.PIPE),
        start_new_session=True,
        **kw,
    ) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            try:
                out, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:  # a grandchild left the group and holds a pipe
                out, err = "", ""
            cmd = " ".join(map(str, args))
            pytest.fail(
                f"{cmd} did not finish in {timeout:.0f} s; its process group was killed.\n"
                f"stdout tail:\n{(out or '')[-2000:]}\nstderr tail:\n{(err or '')[-2000:]}"
            )
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, out, err)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
