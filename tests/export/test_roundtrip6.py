"""E26 (SPEC 11.1): all six fixtures round-trip through `labor check` (mock models) and export.
Slow: run by scripts/acceptance.sh AC1 or `pytest -m slow tests/export/test_roundtrip6.py`."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from manuallabor.contracts.document import Document
from manuallabor.contracts.io import read_json
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.validate import validate_zip
from manuallabor.figures.types import FigureReport
from manuallabor.project import ProjectPaths
from tests.conftest import ALL_FIXTURES, FILES, FIXTURES

LABOR = [sys.executable, "-m", "manuallabor"]


@pytest.mark.slow
@pytest.mark.acc1
def test_e26_six_fixture_round_trip(requires_docling: None, tmp_path: Path) -> None:
    proj = tmp_path / "project-all"
    (proj / "sources").mkdir(parents=True)
    shutil.copyfile(FIXTURES / "project-a" / "project.json", proj / "project.json")
    for k in ALL_FIXTURES:
        shutil.copyfile(FIXTURES / FILES[k], proj / "sources" / FILES[k])
    r = subprocess.run(
        [*LABOR, "check", "--keep", str(proj)], capture_output=True, text=True, timeout=3000
    )
    assert r.returncode == 0, r.stdout + r.stderr[-3000:]
    kept = Path(re.search(r"^kept (.+)$", r.stdout, re.M).group(1))  # type: ignore[union-attr]
    try:
        for k in ("K3", "K12", "K13", "K14", "K15", "K16"):
            assert re.search(rf"^{k}\s.* PASS ", r.stdout, re.M), k
        paths = ProjectPaths(kept)
        (zp,) = sorted((kept / "export").glob("*-kb.zip"))
        assert validate_zip(zp) == []
        import zipfile

        m = Manifest.model_validate_json(zipfile.ZipFile(zp).read("manifest.json"))
        docs = {d.slug: read_json(paths.doc(d.slug).document, Document) for d in m.docs}
        assert set(docs) == set(ALL_FIXTURES)
        assert m.accounting.total_blocks == sum(len(d.block_ids) for d in docs.values())
        k14 = re.search(r"K14.*PASS\s+\d+\s+(.*)", r.stdout)
        assert k14 is not None
        for slug in docs:
            assert [a for a in m.articles if a.source_doc == slug], f"{slug}: no article"
            row = re.search(rf"\b{slug} \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+)", k14.group(1))
            assert row is not None and int(row.group(3)) == 0, f"{slug}: {k14.group(1)}"
            n_figs = len(read_json(paths.doc(slug).figure_report, FigureReport).figures)
            if slug == "scanned":
                # the scanned document's figures are exported (they are in scope by default)
                assert len([f for f in m.figures if f.source_doc == slug]) >= min(1, n_figs)
        assert not m.overrides and m.review_stats.overrides == 0
        # design 11 section 14: on all six fixtures (the scanned one included) the gate's counts
        # partition the scope and match Verify, and the summary partitions the exported blocks
        from manuallabor.export.pipeline import read_state
        from manuallabor.state.store import Store
        from tests.export.test_flags_counts import assert_partition

        store = Store.open(paths)
        try:
            st = assert_partition(paths, store)
        finally:
            store.close()
        assert st.counts is not None and st.counts.blocking == 0
        rec = read_state(paths).export
        assert rec is not None
        r = rec.summary.review
        exported = [b for b, a in m.accounting.assignments.items() if a != "unassigned"]
        assert r.blocks == len(exported) == r.auto_approved + r.approved + r.edited + r.overrides
        assert r.total_blocks == m.accounting.total_blocks == r.blocks + sum(r.left_out.values())
    finally:
        shutil.rmtree(kept.parent, ignore_errors=True)
