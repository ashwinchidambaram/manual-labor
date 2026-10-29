"""Fix-pass tests for module 2: bad bboxes, stale outputs, sidecar metadata, unit branches."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType, Extraction
from manuallabor.contracts.io import read_json_list
from manuallabor.figures.dedupe import DedupeItem, dedupe
from manuallabor.figures.docx_images import DocxImages, UnsupportedImage
from manuallabor.figures.pipeline import run_figures
from manuallabor.project import ProjectPaths
from tests.conftest import Parsed, copy_project
from tests.figures.conftest import index, report, sidecar

requires = pytest.mark.usefixtures("requires_docling")

BAD_BOXES = {
    "offpage": [700.0, 900.0, 800.0, 1000.0],
    "negative": [-50.0, -50.0, -10.0, -10.0],
    "zero": [100.0, 100.0, 100.0, 100.0],
}


def _copy(src: ProjectPaths, tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "proj"
    copy_project(src.root, root)
    return ProjectPaths(root)


# ---- item 1 ----------------------------------------------------------------------------------


@requires
def test_fix1_degenerate_bboxes_fail_only_their_figure(parsed: Parsed, tmp_path: Path) -> None:
    paths = _copy(parsed.paths, tmp_path)
    bp = paths.doc("figures").blocks
    raw = json.loads(bp.read_text())
    figs = [b for b in raw if b["type"] == "figure"]
    assert len(figs) >= 5
    victims = {}
    for b, (name, box) in zip(figs, BAD_BOXES.items(), strict=False):
        b["bbox"] = box
        victims[b["figure_id"]] = name
    bp.write_text(json.dumps(raw))
    lines: list[dict[str, object]] = []
    assert run_figures(paths, only="figures", emit=lines.append) == []
    rep = report(paths, "figures")
    assert {f.figure_id: f.reason for f in rep.failures} == {
        fid: "degenerate_bbox" for fid in victims
    }
    blocks = read_json_list(bp, Block)
    fig_ids = {str(b.figure_id) for b in blocks if b.type == BlockType.figure and b.figure_id}
    ok = {f.figure_id for f in rep.figures}
    assert ok | set(victims) == fig_ids and not ok & set(victims)
    assert len(ok) == len(fig_ids) - 3
    for fid in fig_ids:
        sc = paths.figure_file("figures", fid, "json")
        assert sc.is_file() == (fid in ok), fid


# ---- item 2 ----------------------------------------------------------------------------------


@requires
def test_fix2_force_and_failure_remove_stale_outputs(figproj: ProjectPaths, tmp_path: Path) -> None:
    paths = _copy(figproj, tmp_path)
    d = paths.figure_dir("clean")
    orphan = d / "FIG-clean-p099-01.png"
    orphan.write_bytes(b"x")
    (d / "notes.txt").write_text("keep? no: dir is rebuilt")
    run_figures(paths, only="clean", force=True, emit=lambda _o: None)
    assert not orphan.exists() and not (d / "notes.txt").exists()
    assert len(list(d.glob("FIG-*.json"))) == 3

    # failure: corrupt candidates -> the doc fails and its figure dir is removed
    fj = paths.doc("clean").figures
    fj.write_text(json.dumps(json.loads(fj.read_text())[1:]))
    assert run_figures(paths, only="clean", force=True, emit=lambda _o: None) == ["clean"]
    assert not d.exists()
    assert "clean" not in {e.source_doc for e in index(paths).entries}


@requires
def test_fix2_removed_doc_not_in_index_and_dir_removed(
    figproj: ProjectPaths, tmp_path: Path
) -> None:
    paths = _copy(figproj, tmp_path)
    assert (paths.figure_dir("scanned")).is_dir()
    shutil.rmtree(paths.docs / "scanned")
    assert "scanned" not in paths.list_slugs()
    run_figures(paths, emit=lambda _o: None)
    assert not paths.figure_dir("scanned").exists()
    assert "scanned" not in {e.source_doc for e in index(paths).entries}


# ---- item 3 ----------------------------------------------------------------------------------


@requires
def test_fix3_near_duplicate_sidecar_describes_canonical_file(figproj: ProjectPaths) -> None:
    dup = sidecar(figproj, "figures", "FIG-figures-p007-01")
    canon = sidecar(figproj, "figures", "FIG-figures-p002-01")
    assert dup.file == f"../figures/{canon.id}.png"
    assert (dup.width, dup.height, dup.phash) == (canon.width, canon.height, canon.phash)
    own = next(f for f in report(figproj, "figures").figures if f.figure_id == dup.id)
    assert (dup.page, dup.bbox) == (own.page, own.bbox)
    assert dup.caption_original == own.caption_original
    assert dup.page != canon.page


# ---- item 4 ----------------------------------------------------------------------------------


@requires
def test_fix4_force_recomputes_method_fields_keeps_downstream(
    figproj: ProjectPaths, tmp_path: Path
) -> None:
    paths = _copy(figproj, tmp_path)
    fid = sorted(p.stem for p in paths.figure_dir("clean").glob("FIG-*.json"))[0]
    sc = paths.figure_file("clean", fid, "json")
    good = json.loads(sc.read_text())
    bad = {**good, "confidence": 0.123, "width": 7, "phash": "f" * 16, "tags": ["keep"]}
    sc.write_text(json.dumps(bad))
    run_figures(paths, only="clean", force=True, emit=lambda _o: None)
    after = sidecar(paths, "clean", fid)
    assert after.confidence == good["confidence"]
    assert (after.width, after.phash) == (good["width"], good["phash"])
    assert after.tags == ["keep"]


# ---- item 6 ----------------------------------------------------------------------------------


def _item(fid: str, ph: int, **kw: object) -> DedupeItem:
    base: dict[str, object] = {
        "figure_id": fid,
        "source_doc": fid.split("-")[1],
        "method": Extraction.vector,
        "width": 600,
        "height": 400,
        "png_sha256": "a" * 64,
        "svg_sha256": "b" * 64,
        "phash": f"{ph:016x}",
        "blank": False,
    }
    base.update(kw)
    return DedupeItem(**base)  # type: ignore[arg-type]


def test_fix6_vector_vs_vector_exact_and_near() -> None:
    a, b = _item("FIG-a-p001-01", 0), _item("FIG-b-p001-01", 0)
    e = {x.figure_id: x for x in dedupe([a, b])}
    assert e[b.figure_id].kind == "exact" and e[b.figure_id].duplicate_of == a.figure_id
    # same pixels but different svg -> not exact; phash within threshold -> near
    c = _item("FIG-c-p001-01", 0b111, svg_sha256="c" * 64, png_sha256="d" * 64)
    e = {x.figure_id: x for x in dedupe([a, c])}
    assert e[c.figure_id].kind == "near" and e[c.figure_id].distance == 3
    assert e[c.figure_id].duplicate_of == a.figure_id


def test_fix6_docx_unsupported_format_and_no_image_part(tmp_path: Path) -> None:
    import docx

    from manuallabor.figures.pipeline import _extract_docx
    from manuallabor.parse.types import FigureCandidate

    d = docx.Document()
    d.add_paragraph("hello")
    p = tmp_path / "t.docx"
    d.save(str(p))
    imgs = DocxImages(p)
    with pytest.raises(UnsupportedImage, match="no_image_part"):
        imgs.extract("rIdNope")
    cand = FigureCandidate(
        figure_id="FIG-t-p001-01",
        block_id="b-t-p001-01",
        page=1,
        sources=[],
        image_xrefs=[],
        has_drawings=False,
        docx_image_rid=None,
    )
    with pytest.raises(UnsupportedImage, match="no_image_part"):
        _extract_docx(imgs, cand)

    # a related part that is not a decodable image -> unsupported_format
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    part = Part(PackURI("/word/media/x.emf"), "image/x-emf", b"not an image", d.part.package)
    rid = d.part.relate_to(part, RT.IMAGE)
    d.save(str(p))
    with pytest.raises(UnsupportedImage, match="unsupported_format"):
        DocxImages(p).extract(rid)
