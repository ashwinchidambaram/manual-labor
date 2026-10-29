"""scripts/acceptance.sh step selection and scripts/render_acceptance.py verdicts (review fixes:
`ACCEPT_ONLY` spellings, AC7 needs AC1, an INCOMPLETE record exits non-zero, AC2 needs 100%)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "acceptance.sh"
RENDER = ROOT / "scripts" / "render_acceptance.py"


def dry_run(tmp: Path, *args: str, **env: str) -> list[str]:
    """The script in dry-run mode, with `uv`, `npm`, `ollama` and `shasum` stubbed on PATH and
    every output path in `tmp`: even a script that ignored the dry run could not recurse into
    the test suite or touch docs/ACCEPTANCE.md."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("uv", "npm", "ollama", "shasum"):
        stub = bin_dir / tool
        stub.write_text('#!/bin/sh\necho "stub $0 $*"\nexit 0\n')
        stub.chmod(0o755)
    e = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "ACCEPT_DRY_RUN": "1",
        "ACCEPT_OUT": str(tmp / "out"),
        "ACCEPT_DOC": str(tmp / "ACCEPTANCE.md"),
        "TMPDIR": str(tmp),
        **env,
    }
    r = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "stub " not in r.stdout  # nothing ran, not even a stub
    assert not (tmp / "ACCEPTANCE.md").exists() and not (tmp / "out").exists()
    return re.findall(r"^would run (\d+-\d+)", r.stdout, re.M)


@pytest.mark.parametrize("only", ["AC7", "7", "ac7", "AC7,", " 7 "])
def test_accept_only_takes_ac_names_and_numbers_and_ac7_brings_ac1(
    tmp_path: Path, only: str
) -> None:
    steps = dry_run(tmp_path, ACCEPT_ONLY=only)
    assert steps[0] == "1-1"  # the export AC7 validates comes from AC1's project
    assert {"7-1", "7-2", "7-3"} <= set(steps)
    assert not any(s.split("-")[0] in {"0", "2", "3", "4", "5", "6", "8"} for s in steps)


def test_accept_only_lists_and_skip(tmp_path: Path) -> None:
    assert dry_run(tmp_path, ACCEPT_ONLY="AC3,AC5") == ["3-1", "5-1"]
    assert dry_run(tmp_path, ACCEPT_ONLY="3 5") == ["3-1", "5-1"]
    steps = dry_run(tmp_path, ACCEPT_SKIP="AC4 6 ac0")
    assert "4-1" not in steps and "6-1" not in steps and not any(s.startswith("0-") for s in steps)
    assert "1-1" in steps and "7-1" in steps


def render(d: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER), "render", str(d)], capture_output=True, text=True, cwd=ROOT
    )


def write_step(d: Path, sid: str, out: str, rc: int = 0) -> None:
    (d / f"{sid}.cmd").write_text("cmd\n")
    (d / f"{sid}.out").write_text(out)
    (d / f"{sid}.rc").write_text(f"{rc}\n")


def test_an_incomplete_record_exits_non_zero(tmp_path: Path) -> None:
    (tmp_path / "live.txt").write_text("0\n")
    r = render(tmp_path)
    assert "status: INCOMPLETE" in r.stdout
    assert r.returncode != 0


def test_ac2_is_verified_only_at_full_recall(tmp_path: Path) -> None:
    sys.path.insert(0, str(RENDER.parent))
    try:
        import render_acceptance as ra
    finally:
        sys.path.pop(0)
    write_step(tmp_path, "2-1", "RECALL 23/24 at threshold 0.85\n")
    r = ra.v2(ra.load(tmp_path)[2], False)
    assert r.verdict == ra.FAILED and "23/24" in r.evidence
    write_step(tmp_path, "2-1", "RECALL 24/24 at threshold 0.85\n")
    r = ra.v2(ra.load(tmp_path)[2], False)
    assert r.verdict == ra.VERIFIED and "24/24" in r.evidence


def _ra():  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(RENDER.parent))
    try:
        import render_acceptance as ra
    finally:
        sys.path.pop(0)
    return ra


def test_ac8_needs_the_negative_control(tmp_path: Path) -> None:
    ra = _ra()
    write_step(tmp_path, "8-1", "NAME ID SIZE\nllama3.2:1b x 1 GB\n")
    write_step(tmp_path, "8-2", "K1 nodes fresh  PASS\n")
    write_step(tmp_path, "8-3", "0 network violations\n")
    write_step(tmp_path, "8-4", "ollama=12 other=0\n")
    r = ra.v8(ra.load(tmp_path)[8], True)
    assert r.verdict != ra.VERIFIED and "negative control" in r.evidence
    write_step(tmp_path, "8-5", "negative control: 1.1.1.1:443 blocked and logged (x.log)\n")
    r = ra.v8(ra.load(tmp_path)[8], True)
    assert r.verdict == ra.VERIFIED and "negative control" in r.evidence, r
    write_step(tmp_path, "8-5", "the guard let 1.1.1.1:443 through\n", rc=1)
    assert ra.v8(ra.load(tmp_path)[8], True).verdict == ra.FAILED


def test_ac8_runs_only_live_and_includes_the_negative_control(tmp_path: Path) -> None:
    assert dry_run(tmp_path, ACCEPT_ONLY="AC8") == []  # AC8 runs only with --live
    assert dry_run(tmp_path, "--live", ACCEPT_ONLY="AC8") == ["8-1", "8-2", "8-3", "8-4", "8-5"]
