"""`ingest_run` jobs: uploads are saved under .uploads/<sha>/, ingested, then run to group."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from manuallabor.jobs.runner import JobRunner
from manuallabor.project import ProjectPaths
from manuallabor.state.models import RunPlanIn
from manuallabor.state.store import Store
from tests.conftest import FIXTURES
from tests.jobs.test_runner import wait_for


def test_ingest_run_job(requires_docling: None, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    paths = ProjectPaths(root)
    store = Store.open(paths)
    runner = JobRunner(paths, store, mode="mock")
    runner.start()
    try:
        src = FIXTURES / "clean.pdf"
        job = runner.enqueue(RunPlanIn(to="group"), kind="ingest_run", files=[src])
        assert job.kind == "ingest_run"
        wait_for(lambda: runner.get(job.id).status in ("done", "failed"), 300)
        final = runner.get(job.id)
        assert final.status == "done", final.error
        assert any(o.get("node") == "ingest" for o in runner.log(job.id, 0))
    finally:
        runner.stop()
        store.close()
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    assert (paths.uploads / sha / "clean.pdf").is_file()
    assert paths.list_slugs() == ["clean"]
    assert paths.doc("clean").groups.is_file() and not paths.doc("clean").clean.exists()
