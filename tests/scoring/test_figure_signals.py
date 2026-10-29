"""Test 8: figure_method, figure_resolution, figure_attach_rule."""

from __future__ import annotations

from typing import Any

import pytest

from manuallabor.contracts.enums import AttachRule, BlockType, Extraction
from manuallabor.contracts.io import read_json
from manuallabor.figures.types import DedupeEntry, FigureExtraction, FigureFailure
from manuallabor.scoring.figures import figure_attach_rule, figure_method, figure_resolution
from manuallabor.scoring.types import FigureInputs, ScoreFile
from tests.scoring.conftest import Scored

FID = "FIG-doc-p001-01"


def _ext(method: Extraction = Extraction.native, **kw: Any) -> FigureExtraction:
    base: dict[str, Any] = {
        "figure_id": FID,
        "block_id": "b-doc-p001-01",
        "page": 1,
        "bbox": [72.0, 72.0, 372.0, 272.0],
        "method": method,
        "reason": "single_image",
        "png_sha256": "0" * 64,
        "width": 600,
        "height": 400,
        "phash": "0" * 16,
        "effective_dpi": 150.0,
        "bbox_area_frac": 0.12,
    }
    base.update(kw)
    return FigureExtraction(**base)


def test_method_bases() -> None:
    for m, v in ((Extraction.native, 1.0), (Extraction.vector, 0.95), (Extraction.crop, 0.7)):
        s = figure_method(FigureInputs(extraction=_ext(m)))
        assert s.value == v and s.critical


def test_near_duplicate_cap() -> None:
    dup = DedupeEntry(
        figure_id=FID, source_doc="doc", duplicate_of="FIG-doc-p002-01", kind="near", distance=4
    )
    s = figure_method(FigureInputs(extraction=_ext(), dedupe=dup))
    assert (
        s.value == 0.5
        and s.detail is not None
        and "near-duplicate of FIG-doc-p002-01 (d=4)" in s.detail
    )
    exact = dup.model_copy(update={"kind": "exact", "distance": 0})
    assert figure_method(FigureInputs(extraction=_ext(), dedupe=exact)).value == 1.0


def test_small_region_cap() -> None:
    assert figure_method(FigureInputs(extraction=_ext(bbox=[0, 0, 30, 300]))).value == 0.5
    assert figure_method(FigureInputs(extraction=_ext(bbox_area_frac=0.001))).value == 0.5
    assert figure_method(FigureInputs(extraction=_ext(bbox=None, bbox_area_frac=None))).value == 1.0


def test_failure() -> None:
    f = FigureFailure(figure_id=FID, block_id="b-doc-p001-01", page=1, reason="degenerate_bbox")
    s = figure_method(FigureInputs(failure=f))
    assert s.value == 0.0 and s.critical


def test_resolution() -> None:
    s = figure_resolution(FigureInputs(extraction=_ext(effective_dpi=72.0)))
    assert s is not None and s.value == 0.48 and not s.critical
    assert figure_resolution(FigureInputs(extraction=_ext(effective_dpi=600.0))).value == 1.0  # type: ignore[union-attr]
    assert figure_resolution(FigureInputs(extraction=_ext(effective_dpi=None))) is None


def test_attach_rule() -> None:
    assert figure_attach_rule(FigureInputs(extraction=_ext())) is None
    want = {AttachRule.caption_ref: 1.0, AttachRule.caption_match: 0.9, AttachRule.proximity: 0.6}
    for rule, v in want.items():
        s = figure_attach_rule(FigureInputs(extraction=_ext(), attach_rule=rule, articles=["doc"]))
        assert s is not None and s.value == v and not s.critical
    s = figure_attach_rule(FigureInputs(extraction=_ext(), articles=["doc"]))
    assert s is not None and s.value == 0.4


def _fig_scores(sp: Scored, slug: str) -> dict[str, Any]:
    blocks = {b.id: b for b in sp.blocks(slug)}
    sf = read_json(sp.paths.doc(slug).scores, ScoreFile)
    return {
        s.block_id: (blocks[s.block_id], s)
        for s in sf.blocks
        if blocks[s.block_id].type == BlockType.figure
    }


def test_fixture_figures(scoredproj: Scored) -> None:
    scanned = _fig_scores(scoredproj, "scanned")
    assert scanned and all(s.status == "queued" for _, s in scanned.values())
    figs = _fig_scores(scoredproj, "figures")
    rep = read_json(
        scoredproj.paths.doc("figures").figure_report,
        __import__("manuallabor.figures.types", fromlist=["FigureReport"]).FigureReport,
    )
    method = {f.block_id: f.method for f in rep.figures}
    natives = [s for bid, (_, s) in figs.items() if method[bid] == Extraction.native]
    near = [bid for bid, (_, s) in figs.items() if "near-duplicate" in (s.signals[0].detail or "")]
    assert natives
    for bid, (_, s) in figs.items():
        if method[bid] == Extraction.native and bid not in near:
            assert s.status == "auto_approved", (bid, s.signals)
    assert "b-figures-p007-04" in near
    assert figs["b-figures-p007-04"][1].status == "queued"


@pytest.mark.parametrize("slug", ["figures", "scanned", "clean"])
def test_sidecar_confidence_matches_block(scoredproj: Scored, slug: str) -> None:
    from manuallabor.contracts.figure import FigureRecord

    for b, s in _fig_scores(scoredproj, slug).values():
        rec = read_json(scoredproj.paths.figure_file(slug, b.figure_id, "json"), FigureRecord)
        assert rec.confidence == s.confidence and rec.review.value == s.status
