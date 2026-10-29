"""Test 19: machine status, queue order, and sidecar review protection."""

from __future__ import annotations

import random
from pathlib import Path

from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json, write_json
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import load_scored_blocks, run_score
from manuallabor.scoring.queue import assign_status, build_queue
from tests.conftest import copy_project
from tests.scoring.conftest import Scored, make_block


def test_assign_status() -> None:
    assert assign_status(1.0, True, 0.85) == BlockStatus.queued  # numeric: always reviewed
    assert assign_status(0.85, False, 0.85) == BlockStatus.auto_approved
    assert assign_status(0.849999, False, 0.85) == BlockStatus.queued
    assert assign_status(None, False, 0.85) == BlockStatus.queued
    assert assign_status(0.0, False, 0.0) == BlockStatus.auto_approved


def test_build_queue_order() -> None:
    blocks = [
        make_block("a", n=1, page=10, confidence=0.5),
        make_block("b", n=1, page=9, confidence=0.5),
        make_block("c", n=2, page=1, confidence=None),
        make_block("d", n=3, page=1, confidence=0.1),
        make_block("e", n=4, page=1, confidence=0.99, status=BlockStatus.auto_approved),
        make_block("h", n=5, page=1, confidence=0.0, type=BlockType.header),
        make_block("f", n=6, page=1, confidence=0.0, type=BlockType.footer),
        make_block("g", n=7, page=1, confidence=0.7, status=BlockStatus.approved),
    ]
    want = ["b-doc-p001-02", "b-doc-p001-03", "b-doc-p009-01", "b-doc-p010-01"]
    assert build_queue(blocks) == want
    for seed in range(5):
        shuffled = list(blocks)
        random.Random(seed).shuffle(shuffled)
        assert build_queue(shuffled) == want


def test_fixture_queue(scoredproj: Scored) -> None:
    blocks = load_scored_blocks(scoredproj.paths, "clean")
    q = build_queue(blocks)
    by_id = {b.id: b for b in blocks}
    assert q and all(by_id[i].status == BlockStatus.queued for i in q)
    confs = [by_id[i].confidence for i in q]
    assert confs == sorted(confs, key=lambda c: -1.0 if c is None else c)


def test_sidecar_review_not_overwritten(scoredproj: Scored, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    copy_project(scoredproj.paths.root, root)
    paths = ProjectPaths(root)
    fid = "FIG-scanned-p005-01"
    sc = paths.figure_file("scanned", fid, "json")
    rec = read_json(sc, FigureRecord)
    assert rec.review == BlockStatus.queued
    write_json(sc, rec.model_copy(update={"review": BlockStatus.approved, "confidence": 1.0}))
    assert run_score(paths, force=True, emit=lambda _o: None) == []
    after = read_json(sc, FigureRecord)
    assert after.review == BlockStatus.approved  # human decision kept
    assert after.confidence == rec.confidence  # machine confidence restored
