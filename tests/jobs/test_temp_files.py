"""Temp files written outside the worker lock must survive the job's start-up cleaner, and their
leftovers are removed only by the side that owns them (code review F1 and F16).

The rule (ARCHITECTURE section 4, design 07 section 14): `*.tmp` is written only under the worker
lock and `clean_stray_tmp` removes leftovers at every job start. Anything written outside that
lock (API projections, learning snapshots, page renders, uploads) uses a unique `*.part` name per
call, and its leftovers are removed by `clean_stray_parts` at `labor serve` start-up, only while
both the project lock and the worker lock are held."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from manuallabor.contracts import io as cio
from manuallabor.jobs import executor
from manuallabor.jobs.executor import clean_stray_tmp
from manuallabor.project import ProjectPaths
from manuallabor.state import learning as learning_mod
from manuallabor.state import projections
from manuallabor.state.learning import LearningService
from manuallabor.state.lock import ProjectLock


def _cleaner_runs_before_replace(
    monkeypatch: pytest.MonkeyPatch, paths: ProjectPaths, module: object, name: str
) -> list[int]:
    """Make `module.os.<name>` run the job's start-up cleaner first: the worst interleaving of a
    job starting while the API is between writing its temp file and renaming it."""
    real = getattr(os, name)
    hits: list[int] = []

    def racing(src: object, dst: object) -> None:
        hits.append(clean_stray_tmp(paths))
        real(src, dst)

    monkeypatch.setattr(module, "os", _OsProxy(name, racing), raising=True)
    return hits


class _OsProxy:
    """`os` with one function replaced, so the patch stays local to one module."""

    def __init__(self, name: str, fn: object) -> None:
        self._name = name
        self._fn = fn

    def __getattr__(self, attr: str) -> object:
        if attr == self._name:
            return self._fn
        return getattr(os, attr)


def test_job_cleaner_spares_an_in_flight_projection_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(tmp_path)
    target = paths.doc("clean").group_overrides
    hits = _cleaner_runs_before_replace(monkeypatch, paths, cio, "replace")
    assert projections.write_if_differs(target, "[]\n") is True
    assert target.read_text(encoding="utf-8") == "[]\n"
    assert hits == [0], "the job cleaner deleted the API's in-flight projection temp file"


def test_job_cleaner_spares_an_in_flight_learning_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(tmp_path)

    class _Store:
        def now(self) -> str:
            return "2026-10-30T00:00:00Z"

        def get_snapshot(self, _sid: str) -> None:
            return None

    svc = LearningService(paths, _Store())  # type: ignore[arg-type]
    hits = _cleaner_runs_before_replace(monkeypatch, paths, learning_mod, "rename")
    final = svc._write_snapshot("001", {"cleanup.json": "{}\n"}, None, None, None, {})
    assert (final / "cleanup.json").read_text(encoding="utf-8") == "{}\n"
    assert (final / "manifest.json").is_file()
    assert hits == [0], "the job cleaner deleted the API's in-flight snapshot staging dir"
    assert [p.name for p in (paths.learning / "snapshots").iterdir()] == ["001"]


def test_job_cleaner_survives_a_temp_file_renamed_under_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer may rename its temp file between the cleaner's `rglob` and its `unlink`."""
    paths = ProjectPaths(tmp_path)
    stray = paths.doc("clean").root / "blocks.json.tmp"
    stray.parent.mkdir(parents=True)
    stray.write_text("x", encoding="utf-8")
    real_is_file = Path.is_file

    def vanishing(self: Path) -> bool:
        ok = real_is_file(self)
        if self == stray:
            self.unlink()  # the writer's os.replace happened right here
        return ok

    monkeypatch.setattr(Path, "is_file", vanishing)
    clean_stray_tmp(paths)  # must not raise FileNotFoundError
    assert not stray.exists()


def test_outside_the_lock_writes_use_a_unique_part_name_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = os.replace

    def spy(src: object, dst: object) -> None:
        seen.append(Path(str(src)).name)
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(cio, "os", _OsProxy("replace", spy))
    target = ProjectPaths(tmp_path).doc("clean").attach_overrides
    projections.write_if_differs(target, "[1]\n")
    projections.write_if_differs(target, "[2]\n")
    cio.write_text_atomic(target, "[3]\n")
    assert len(seen) == 3 and len(set(seen)) == 3, seen
    assert all(s.startswith("attach_overrides.json.") for s in seen)
    assert seen[0].endswith(".part") and seen[1].endswith(".part")
    assert seen[2].endswith(".tmp")  # the default is for writers under the worker lock


def test_concurrent_projection_writes_of_one_file_all_succeed(tmp_path: Path) -> None:
    target = ProjectPaths(tmp_path).doc("clean").group_overrides
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def write(i: int) -> None:
        barrier.wait()
        try:
            for j in range(20):
                projections.write_if_differs(target, f"[{i}, {j}]\n")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[0]
    assert not list(target.parent.glob("*.part")) and not list(target.parent.glob("*.tmp"))


# -- the serve-side cleaner (F16) ---------------------------------------------------------------


def _leftovers(paths: ProjectPaths) -> dict[str, Path]:
    d = paths.doc("clean")
    files = {
        "projection_part": d.root / "group_overrides.json.0123abcd.part",
        "render_part": d.root / "pages_view" / "p001-150.png.0123abcd.part",
        "figure_part": paths.figures_root / "clean" / "FIG-x.json.0123abcd.part",
        "learning_part": paths.learning / "cleanup.json.0123abcd.part",
        "incoming": paths.uploads / ".incoming-0123abcd.part",
        "incoming_legacy": paths.uploads / ".incoming-0123456789ab",
        "upload_live": paths.uploads / ("a" * 64) / "manual.pdf",
        "upload_done": paths.uploads / ("b" * 64) / "other.pdf",
        "stage_tmp": d.root / "blocks.json.tmp",
        "keep_json": d.root / "group_overrides.json",
    }
    for p in files.values():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    for name in (".part-002-0123abcd", ".tmp-003"):
        staging = paths.learning / "snapshots" / name
        staging.mkdir(parents=True)
        (staging / "cleanup.json").write_text("{}", encoding="utf-8")
    (paths.learning / "snapshots" / "001").mkdir()
    return files


def test_clean_stray_parts_removes_only_outside_the_lock_leftovers(tmp_path: Path) -> None:
    from manuallabor.jobs.executor import clean_stray_parts

    paths = ProjectPaths(tmp_path)
    f = _leftovers(paths)
    n = clean_stray_parts(paths, keep_uploads={f["upload_live"]})
    gone = {k for k, p in f.items() if not p.exists()}
    assert gone == {
        "projection_part",
        "render_part",
        "figure_part",
        "learning_part",
        "incoming",
        "incoming_legacy",
        "upload_done",
    }
    assert not (paths.uploads / ("b" * 64)).exists(), "an ingested upload dir was left behind"
    assert sorted(p.name for p in (paths.learning / "snapshots").iterdir()) == ["001"]
    assert n == len(gone) + 2  # plus the two snapshot staging dirs


def test_leftovers_are_kept_while_a_worker_holds_its_lock(tmp_path: Path) -> None:
    from manuallabor.jobs.executor import clean_leftovers_at_start

    paths = ProjectPaths(tmp_path)
    f = _leftovers(paths)
    worker = ProjectLock(paths.worker_lock, cmd="a live worker")
    worker.acquire()
    try:
        assert clean_leftovers_at_start(paths, live_job_ids=[]) is None
    finally:
        worker.release()
    assert all(p.exists() for p in f.values()), "a live worker's .part files were deleted"
    # no live job: both upload dirs go too (8 entries), plus the 2 staging dirs
    assert clean_leftovers_at_start(paths, live_job_ids=[]) == 10


def test_uploads_of_queued_jobs_are_kept(tmp_path: Path) -> None:
    import json

    from manuallabor.jobs.executor import clean_leftovers_at_start

    paths = ProjectPaths(tmp_path)
    f = _leftovers(paths)
    plan = paths.job_plan("job-000007")
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"files": [str(f["upload_live"])]}), encoding="utf-8")
    clean_leftovers_at_start(paths, live_job_ids=["job-000007"])
    assert f["upload_live"].is_file()
    assert not f["upload_done"].exists()


def test_executor_exports_both_cleaners() -> None:
    assert {"clean_stray_tmp", "clean_stray_parts", "clean_leftovers_at_start"} <= set(
        executor.__all__
    )


def test_serve_start_up_cleans_before_the_runner_starts(tmp_path: Path) -> None:
    """`labor serve` calls the cleaner with the ids of queued and running jobs."""
    import json
    from types import SimpleNamespace

    from manuallabor.serve import _clean_leftovers

    paths = ProjectPaths(tmp_path)
    f = _leftovers(paths)
    plan = paths.job_plan("job-000003")
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"files": [str(f["upload_live"])]}), encoding="utf-8")
    asked: list[set[str]] = []

    def listing(status: set[str]) -> list[SimpleNamespace]:
        asked.append(status)
        return [SimpleNamespace(id="job-000003")]

    _clean_leftovers(paths, SimpleNamespace(runner=SimpleNamespace(list=listing)))  # type: ignore[arg-type]
    assert asked == [{"queued", "running"}]
    assert f["upload_live"].is_file() and f["stage_tmp"].is_file()
    assert not f["projection_part"].exists() and not f["upload_done"].exists()
