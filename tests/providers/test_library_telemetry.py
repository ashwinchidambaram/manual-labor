"""No third-party telemetry (invariant 6; design 06 section 4).

onnxruntime 1.31 (RapidOCR's runtime) starts Microsoft 1DS telemetry on macOS and Linux when it
is imported: it writes `~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`
(a device id and an event database) and uploads from a background thread. Its teardown also hung
two spawned render workers at exit (spinning in `TransmissionPolicyManager::handleStop`), which
stalled a full test run. `ORT_DISABLE_TELEMETRY=1`, set by `import manuallabor` before anything
can import onnxruntime, turns the 1DS provider off entirely; `disable_telemetry_events()` alone
does not stop the store being created."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from manuallabor import telemetry
from manuallabor.parse.render import OcrPool

ROOT = Path(__file__).resolve().parents[2]
# onnxruntime also stays quiet under CI or its own unit tests: strip those so the control bites
_QUIET = {
    "CI", "TF_BUILD", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS", "JENKINS_URL",
    "CODEBUILD_BUILD_ID", "BUILDKITE", "TEAMCITY_VERSION", "APPVEYOR", "BITBUCKET_BUILD_NUMBER",
    "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI", "ORT_RUNNING_UNIT_TESTS", telemetry.ORT_ENV,
}  # fmt: skip


def _child(home: Path, code: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _QUIET}
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=120,
    )  # fmt: skip


def _ort_files(home: Path) -> list[str]:
    return sorted(str(p.relative_to(home)) for p in home.rglob("*") if "onnxruntime" in str(p))


def test_importing_manuallabor_first_keeps_onnxruntime_from_writing_telemetry(
    tmp_path: Path,
) -> None:
    pytest.importorskip("onnxruntime")
    control, ours = tmp_path / "control", tmp_path / "ours"
    control.mkdir()
    ours.mkdir()
    r = _child(control, "import onnxruntime")
    assert r.returncode == 0, r.stderr
    if not _ort_files(control):  # a build without the 1DS provider: nothing to prove
        pytest.skip("this onnxruntime writes no telemetry store")
    r = _child(
        ours,
        "import os, manuallabor, onnxruntime\n"
        "assert os.environ['ORT_DISABLE_TELEMETRY'] == '1'\n"
        "from manuallabor.parse.ocr import _rapid_engine\n",
    )
    assert r.returncode == 0, r.stderr
    assert _ort_files(ours) == []


def test_a_user_value_cannot_turn_it_back_on(tmp_path: Path) -> None:
    home = tmp_path / "h"
    home.mkdir()
    code = (
        "import os\nos.environ['ORT_DISABLE_TELEMETRY'] = '0'\n"
        "import manuallabor\nprint(os.environ['ORT_DISABLE_TELEMETRY'])"
    )
    r = _child(home, code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1"


def test_a_spawned_pool_worker_has_telemetry_off_without_inheriting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(telemetry.ORT_ENV, raising=False)  # the worker must set it itself
    pool = OcrPool(1)
    try:
        assert pool.executor().submit(telemetry.telemetry_disabled).result(timeout=120)
    finally:
        pool.close()
