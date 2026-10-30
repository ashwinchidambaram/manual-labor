"""Module 2 gate tests (design 12, tests 1-12 and 15) against the fixture projects."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType, Extraction
from manuallabor.contracts.figure import FigureRecord, parse_figure_file
from manuallabor.contracts.io import read_json_list
from manuallabor.figures.encode import sha256_bytes
from manuallabor.figures.native import agreement
from manuallabor.parse import geometry as g
from manuallabor.project import ProjectPaths
from tests.figures.conftest import GT_STEMS, entry, index, load_gt, report, sidecar
from tests.fixtures.gen.ground_truth import pixel_sha256

pytestmark = pytest.mark.usefixtures("requires_docling")

DOCX_STEM = "manual"


def _png(paths: ProjectPaths, slug: str, fid: str) -> bytes:
    return paths.figure_file(slug, fid, "png").read_bytes()


def _pixels(png: bytes) -> str:
    """GT `source_image.sha256` is a pixel hash (see `pixel_sha256`), not a PNG-file hash."""
    return pixel_sha256(Image.open(io.BytesIO(png)))


@pytest.mark.acc3
def test_01_figures_methods_match_gt(figproj: ProjectPaths) -> None:
    gt = load_gt("figures")["figures"]
    assert len(gt) == 14
    ok = 0
    for f in gt:
        sc = sidecar(figproj, "figures", f["expected_id"])
        if sc.extraction.value == f["expected_extraction"]:
            ok += 1
        e = entry(figproj, "figures", f["expected_id"])
        assert e.reason == ("single_image" if sc.extraction == Extraction.native else "vector_only")
        assert e.method == sc.extraction
    by_method = Counter(sidecar(figproj, "figures", f["expected_id"]).extraction.value for f in gt)
    print(  # SPEC 11.3 evidence
        f"FIGURES native={by_method['native']} vector={by_method['vector']} "
        f"crop={by_method['crop']} (native+vector {ok}/{len(gt)})"
    )
    assert ok / len(gt) >= 0.95
    assert ok == 14


def test_02_twocol(figproj: ProjectPaths) -> None:
    e = entry(figproj, "twocol", "FIG-twocol-p004-01")
    assert (e.method, e.reason, e.crop_source) == (Extraction.crop, "image_with_drawings", "render")
    for fid in ("FIG-twocol-p002-01", "FIG-twocol-p002-02"):
        assert sidecar(figproj, "twocol", fid).extraction == Extraction.native


def test_03_native_pixels_equal_gt(figproj: ProjectPaths) -> None:
    n = 0
    for stem in ("figures", "twocol", "clean"):
        for f in load_gt(stem)["figures"]:
            src = f["source_image"]
            if src is None or f["expected_extraction"] != "native":
                continue
            fid = f["expected_id"]
            data = _png(figproj, stem, fid)
            e = entry(figproj, stem, fid)
            assert (e.width, e.height) == (src["width"], src["height"]), fid
            assert _pixels(data) == src["sha256"], f"{fid}: PNG pixels differ from GT"
            n += 1
    assert n == 8 + 2 + 3


def test_04_vector_svg(figproj: ProjectPaths) -> None:
    gt = [f for f in load_gt("figures")["figures"] if f["expected_extraction"] == "vector"]
    assert len(gt) == 6
    for f in gt:
        fid = f["expected_id"]
        svg_bytes = figproj.figure_file("figures", fid, "svg").read_bytes()
        root = ET.fromstring(svg_bytes)
        tags = [el.tag.split("}")[-1] for el in root.iter()]
        assert tags.count("path") >= 1 and tags.count("image") == 0, fid
        img = Image.open(io.BytesIO(_png(figproj, "figures", fid)))
        assert img.width >= 1000
        gray = np.asarray(img.convert("L"))
        ink = float((gray < 245).mean())
        assert 0.005 <= ink <= 0.60, (fid, ink)
        doc = pymupdf.open(stream=svg_bytes, filetype="svg")
        pix = doc[0].get_pixmap(dpi=72, alpha=False)
        render = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        mad, _ = agreement(render, img)
        assert mad <= 6.0, (fid, mad)


def test_05_dedupe_in_figures(figproj: ProjectPaths) -> None:
    entries = {e.figure_id: e for e in index(figproj).entries if e.source_doc == "figures"}
    p6 = entries["FIG-figures-p006-01"]
    assert (p6.duplicate_of, p6.kind) == ("FIG-figures-p002-01", "exact")
    assert sidecar(figproj, "figures", "FIG-figures-p006-01").file == (
        "../figures/FIG-figures-p002-01.png"
    )
    p7 = entries["FIG-figures-p007-01"]
    assert (p7.duplicate_of, p7.kind) == ("FIG-figures-p002-01", "near")
    assert p7.distance is not None and p7.distance <= 8
    assert sidecar(figproj, "figures", "FIG-figures-p007-01").file == (
        "../figures/FIG-figures-p002-01.png"
    )
    others = [e for fid, e in entries.items() if fid not in {p6.figure_id, p7.figure_id}]
    assert all(e.duplicate_of is None for e in others)
    base = figproj.figure_dir("figures")
    targets = {(base / sidecar(figproj, "figures", fid).file).resolve() for fid in entries}
    assert len(targets) == 12


def test_06_twin_cross_slug(twin: ProjectPaths) -> None:
    """The copy writes its own files on disk (design 13.10); the original's PNGs are untouched.

    Export dedupes to one file: every copy sidecar's `file` points at the canonical's PNG, so
    only the canonical files are copied into `images/`.
    """
    orig = report(twin, "figures")
    for f in orig.figures:
        data = twin.figure_file("figures", f.figure_id, "png").read_bytes()
        assert sha256_bytes(data) == f.png_sha256, f.figure_id
        own = twin.figure_file(
            "figures-copy", f.figure_id.replace("figures-", "figures-copy-", 1), "png"
        )
        assert own.is_file()
    rep = report(twin, "figures-copy")
    assert len(rep.figures) == 14
    entries = {e.figure_id: e for e in index(twin).entries if e.source_doc == "figures-copy"}
    for f in rep.figures:
        sc = sidecar(twin, "figures-copy", f.figure_id)
        e = entries[f.figure_id]
        # p7-01 is only a near duplicate of the canonical p2-01 (its twin copy inherits that)
        want = "near" if f.figure_id.endswith("p007-01") else "exact"
        assert e.kind == want, f.figure_id
        assert sc.file.startswith("../figures/") and sc.file.endswith(".png")
        if sc.svg is not None:
            assert sc.svg.startswith("../figures/") and sc.svg.endswith(".svg")
    for page, n in ((2, 1), (6, 1), (7, 1)):
        fid = f"FIG-figures-copy-p{page:03d}-{n:02d}"
        assert entries[fid].duplicate_of == "FIG-figures-p002-01"
    # the manifest-side contract: duplicate_of points at roots and file paths agree with it
    from manuallabor.contracts.manifest import ManifestFigure

    mf = {}
    for e in index(twin).entries:
        mf[e.figure_id] = ManifestFigure(
            id=e.figure_id,
            sidecar=f"images/{e.source_doc}/{e.figure_id}.json",
            file=sidecar(twin, e.source_doc, e.figure_id).file,
            source_doc=e.source_doc,
            duplicate_of=e.duplicate_of,
        )
    for f in mf.values():
        if f.duplicate_of is not None:
            assert mf[f.duplicate_of].duplicate_of is None
            assert parse_figure_file(f.id, f.file, ("png", "svg")) == (
                mf[f.duplicate_of].source_doc,
                f.duplicate_of,
            )


def test_07_cross_doc_dedupe(figproj: ProjectPaths) -> None:
    ent = {e.figure_id: e for e in index(figproj).entries}
    for tid, cid in (
        ("FIG-twocol-p002-01", "FIG-clean-p006-01"),
        ("FIG-twocol-p002-02", "FIG-clean-p006-02"),
    ):
        assert (ent[tid].duplicate_of, ent[tid].kind) == (cid, "exact")
    for sid in ("FIG-scanned-p005-01", "FIG-scanned-p006-01", "FIG-scanned-p006-02"):
        assert ent[sid].kind == "near" and ent[sid].duplicate_of is not None
        assert ent[sid].duplicate_of.startswith("FIG-clean-"), sid
    comp = ent["FIG-twocol-p004-01"]
    assert comp.duplicate_of is None
    for e in index(figproj).entries:
        if e.source_doc in ("manual", "figures") and e.duplicate_of is not None:
            assert e.duplicate_of.startswith(f"FIG-{e.source_doc}-"), e.figure_id


def test_08_sidecars_validate(figproj: ProjectPaths) -> None:
    for slug in figproj.list_slugs():
        for f in report(figproj, slug).figures:
            sc = sidecar(figproj, slug, f.figure_id)
            assert isinstance(sc, FigureRecord)
            base = figproj.figure_dir(slug)
            assert (base / sc.file).resolve().is_file()
            if sc.svg is not None:
                assert (base / sc.svg).resolve().is_file()


def test_09_no_silent_drops(figproj: ProjectPaths) -> None:
    for slug in figproj.list_slugs():
        blocks = read_json_list(figproj.doc(slug).blocks, Block)
        fig_ids = sorted(str(b.figure_id) for b in blocks if b.type == BlockType.figure)
        rep = report(figproj, slug)
        got = [f.figure_id for f in rep.figures] + [f.figure_id for f in rep.failures]
        assert sorted(got) == fig_ids, slug
        assert rep.failures == []
        on_disk = sorted(p.stem for p in figproj.figure_dir(slug).glob("FIG-*.json"))
        assert on_disk == sorted(f.figure_id for f in rep.figures)
    assert report(figproj, "tables").figures == []
    assert not list(figproj.figure_dir("tables").glob("FIG-*"))


def test_10_clean(figproj: ProjectPaths) -> None:
    gt = load_gt("clean")["figures"]
    assert len(gt) == 3
    for f in gt:
        e = entry(figproj, "clean", f["expected_id"])
        assert e.method == Extraction.native
        assert _pixels(_png(figproj, "clean", f["expected_id"])) == f["source_image"]["sha256"]


def test_11_scanned(figproj: ProjectPaths) -> None:
    for f in load_gt("scanned")["figures"]:
        fid = f["expected_id"]
        e = entry(figproj, "scanned", fid)
        assert (e.method, e.reason, e.crop_source) == (Extraction.crop, "scanned_page", "raster")
        assert e.effective_dpi == 300
        assert e.render_rect is not None
        want = [f["bbox"][0] - 2, f["bbox"][1] - 2, f["bbox"][2] + 2, f["bbox"][3] + 2]
        assert g.iou(e.render_rect, want) >= 0.9, (fid, e.render_rect, want)
        img = Image.open(io.BytesIO(_png(figproj, "scanned", fid))).convert("L")
        arr = np.asarray(img)
        # the crop's last rows are the 2 pt margin below the figure: no caption ink there
        bottom = arr[-3:]
        assert float((bottom < 128).mean()) < 0.01, fid


def test_12_manual_docx(figproj: ProjectPaths) -> None:
    from docx import Document as DocxDocument

    part_blobs = {
        sha256_bytes(p.blob)
        for p in DocxDocument(str(FIXTURES_DIR / "manual.docx")).part.related_parts.values()
        if getattr(p, "content_type", "") == "image/png"
    }
    for f in load_gt("manual")["figures"]:
        fid = f["expected_id"]
        e = entry(figproj, "manual", fid)
        sc = sidecar(figproj, "manual", fid)
        assert (e.method, e.bbox, sc.bbox) == (Extraction.native, None, None)
        assert sc.page == f["page"]
        png = _png(figproj, "manual", fid)
        # pixels match the GT source; the bytes are the DOCX part's blob, copied unchanged
        assert _pixels(png) == f["source_image"]["sha256"] and sha256_bytes(png) in part_blobs
        assert e.effective_dpi == 300


def test_15_captions_match_gt(figproj: ProjectPaths) -> None:
    n = 0
    for stem in GT_STEMS:
        for f in load_gt(stem)["figures"]:
            e = entry(figproj, stem, f["expected_id"])
            assert e.caption_original == f["caption"], (f["expected_id"], e.caption_original)
            assert sidecar(figproj, stem, f["expected_id"]).caption_original == f["caption"]
            n += 1
    assert n == 14 + 3 + 3 + 3 + 2
    # trimming of a fused caption block is covered by unit test 16 (module 1 no longer fuses it)
    sc = entry(figproj, "scanned", "FIG-scanned-p006-02")
    assert sc.caption_original == "Figure 2. Idler pulley mounting positions."


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
