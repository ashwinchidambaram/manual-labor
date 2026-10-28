"""Test 31: ingest/parse CLI output and idempotency."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from manuallabor.cli import app
from tests.parse.conftest import FIXTURES

REQUIRED = {"doc", "stage", "status", "pages", "elapsed_ms", "detail"}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted((root / "docs").rglob("*.json"))
    }


def test_31_cli_ingest_parse(requires_docling: None, tmp_path: Path) -> None:
    runner = CliRunner()
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copyfile(FIXTURES / "project-a" / "project.json", proj / "project.json")
    r = runner.invoke(app, ["ingest", str(proj), str(FIXTURES / "clean.pdf")])
    assert r.exit_code == 0, r.output
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    assert lines and all({"doc", "status", "kind", "pages", "file"} <= set(x) for x in lines)

    first = runner.invoke(app, ["parse", str(proj)])
    assert first.exit_code == 0, first.output
    parsed_lines = [json.loads(x) for x in first.stdout.splitlines() if x.strip()]
    assert all(set(x) >= REQUIRED for x in parsed_lines)
    assert {x["stage"] for x in parsed_lines} >= {"pymupdf", "docling", "merge", "write"}
    assert all(x["status"] in ("done", "skip", "warning") for x in parsed_lines)
    snap = _snapshot(proj)

    second = runner.invoke(app, ["parse", str(proj)])
    assert second.exit_code == 0
    again = [json.loads(x) for x in second.stdout.splitlines() if x.strip()]
    assert again and all(x["status"] == "skip" for x in again)
    assert _snapshot(proj) == snap

    forced = runner.invoke(app, ["parse", str(proj), "--force"])
    assert forced.exit_code == 0
    assert _snapshot(proj) == snap
