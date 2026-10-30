"""The bounded child-process helper fails the test and kills the whole group on a hang."""

from __future__ import annotations

import os
import sys
import time

import pytest

from tests.subproc import run_bounded

HANG = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
    "print(g.pid, flush=True)\n"
    "time.sleep(600)\n"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_hung_child_fails_the_test_and_its_group_is_killed() -> None:
    t0 = time.monotonic()
    with pytest.raises(pytest.fail.Exception, match="did not finish in 2 s") as info:
        run_bounded([sys.executable, "-c", HANG], timeout=2)
    assert time.monotonic() - t0 < 30
    grandchild = int(str(info.value).split("stdout tail:\n", 1)[1].split()[0])
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(grandchild)


def test_a_normal_child_returns_its_output() -> None:
    r = run_bounded([sys.executable, "-c", "print('ok')"], timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "ok"
