"""The render/OCR pool's shutdown is bounded (design 01 section 11.1).

Seen in a full test run: `labor run --to group` finished its renders, then both spawned workers
spun forever in process exit (onnxruntime telemetry teardown), the parent waited forever in the
pool's shutdown join and pytest waited forever on the pipes. `OcrPool.close` now asks the workers
to exit, waits a bounded time and terminates (then kills) any that is still alive, logging it."""

from __future__ import annotations

import logging
import time

import pytest

from manuallabor.parse import render
from manuallabor.parse.render import OcrPool
from tests.parse import pool_children


def test_close_returns_and_terminates_a_worker_that_will_not_exit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = OcrPool(1)
    assert pool.executor().submit(pool_children.hang_at_exit, 7).result(timeout=120) == 7
    procs = pool.processes()
    assert len(procs) == 1
    t0 = time.monotonic()
    with caplog.at_level(logging.WARNING, logger=render.__name__):
        pool.close(timeout=2.0)
    assert time.monotonic() - t0 < 15
    assert render._wait_exit(procs, 5.0) == []  # exited (read from the sentinel, not waitpid)
    assert any("did not exit" in r.getMessage() for r in caplog.records), caplog.text


def test_close_leaves_well_behaved_workers_alone(caplog: pytest.LogCaptureFixture) -> None:
    pool = OcrPool(2)
    futs = [pool.executor().submit(pool_children.echo, i) for i in range(4)]
    assert [f.result(timeout=120) for f in futs] == [0, 1, 2, 3]
    procs = pool.processes()
    with caplog.at_level(logging.WARNING, logger=render.__name__):
        pool.close(timeout=30.0)
    assert render._wait_exit(procs, 5.0) == []
    assert not [r for r in caplog.records if "did not exit" in r.getMessage()]


def test_close_without_a_pool_is_a_noop() -> None:
    OcrPool(1).close()
