"""Global learning publish: concurrent publishes get distinct ids and never touch each other's
staging folder (backend review 2 finding 5, design 07 section 14.1).

The id was read from `latest_global()` outside any lock and staged in `.tmp-<id>`, removed first
with `rmtree`: two publishes picked the same id, the second deleted the first's files mid-write,
and one rename failed or published partial files."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from manuallabor.state.learning import publish_global

N = 8


def _snapshot(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / "cleanup.json").write_text(json.dumps({"snapshot": "snapshot:001", "examples": []}))
    (d / "manifest.json").write_text(json.dumps({"id": "001", "origin": "project"}))
    return d


def test_concurrent_publishes_get_distinct_complete_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANUALLABOR_HOME", str(tmp_path / "home"))
    src = _snapshot(tmp_path / "snap")
    gdir = tmp_path / "home" / "learning" / "snapshots"
    gdir.mkdir(parents=True)
    foreign = gdir / ".part-099-0123abcd"  # another publish's staging folder, mid-write
    foreign.mkdir()
    (foreign / "cleanup.json").write_text("{}")
    start = threading.Barrier(N)
    got: list[str] = []
    errors: list[BaseException] = []

    def one(i: int) -> None:
        start.wait()
        try:
            gid = publish_global(src, origin=f"project:p{i}", published_at="2026-10-30T00:00:00Z")
            got.append(gid)
        except BaseException as exc:  # noqa: BLE001 - the test reports every failure
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert sorted(got) == [f"{i:03d}" for i in range(1, N + 1)]
    for gid in got:
        d = gdir / gid
        assert json.loads((d / "manifest.json").read_text())["id"] == gid
        assert json.loads((d / "cleanup.json").read_text())["snapshot"] == f"global:{gid}"
    assert (foreign / "cleanup.json").read_text() == "{}"  # never touched
    leftovers = sorted(p.name for p in gdir.iterdir() if p.name.startswith("."))
    assert leftovers == [".part-099-0123abcd", ".publish.lock"]
