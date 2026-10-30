"""Functions the render-pool tests submit to spawned workers (importable by the child)."""

from __future__ import annotations

import atexit
import time


def echo(x: int) -> int:
    return x


def hang_at_exit(x: int) -> int:
    """Make this worker refuse to exit: an exit handler that never returns, like the
    onnxruntime telemetry teardown that spun forever."""
    atexit.register(time.sleep, 3600)
    return x
