"""Third-party telemetry stays off (invariant 6; design 06 section 4).

onnxruntime (RapidOCR's runtime) ships Microsoft 1DS telemetry on macOS and Linux from 1.31: on
import it writes a device id and an event database under
`~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/` and uploads from a
background thread, and its exit-time teardown hung spawned render workers (design 01 section
11.1). Only the environment variable stops the provider from starting; the Python call
`onnxruntime.disable_telemetry_events()` mutes events but the store is created anyway. So
`import manuallabor` sets the variable before anything can import onnxruntime, every spawned
pool worker sets it again in its initializer, and a user value never turns it back on. This
module imports nothing heavy."""

from __future__ import annotations

import contextlib
import os
import sys

__all__ = ["ORT_ENV", "disable_library_telemetry", "telemetry_disabled"]

ORT_ENV = "ORT_DISABLE_TELEMETRY"


def disable_library_telemetry() -> None:
    """Turn third-party telemetry off for this process and the processes it starts. Idempotent;
    when onnxruntime is already imported, also mutes its events (belt and braces)."""
    os.environ[ORT_ENV] = "1"
    ort = sys.modules.get("onnxruntime")
    off = getattr(ort, "disable_telemetry_events", None)
    if callable(off):
        # an older or stub build may fail here: the environment variable is what counts
        with contextlib.suppress(Exception):
            off()


def telemetry_disabled() -> bool:
    """Whether this process has third-party telemetry off (a picklable probe for pool workers)."""
    return os.environ.get(ORT_ENV) == "1"
