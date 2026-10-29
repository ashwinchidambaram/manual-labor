"""Figure extraction stage: per-document extraction, project-wide dedupe, sidecars (design 9-11)."""

from __future__ import annotations

import importlib.metadata as md
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType, DocKind, Extraction
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import (
    canonical_json,
    dump_json,
    read_json,
    read_json_list,
)
from manuallabor.figures.captions import CaptionMatch, find_captions
from manuallabor.figures.crop import CropResult, DecodeCache, crop_region
from manuallabor.figures.decide import decide
from manuallabor.figures.dedupe import DedupeItem, dedupe, is_blank, phash_hex
from manuallabor.figures.docx_images import DocxImages, UnsupportedImage
from manuallabor.figures.encode import (
    encode_png,
    sha256_bytes,
    write_if_changed,
)
from manuallabor.figures.mu import pymupdf
from manuallabor.figures.native import effective_dpi, extract_native
from manuallabor.figures.page_content import load_page_content
from manuallabor.figures.sidecar import build_record
from manuallabor.figures.types import (
    FIGURES_ALGO_VERSION,
    NEAR_DUP_MAX_DIST,
    RENDER_DPI,
    Decision,
    DedupeEntry,
    FigureExtraction,
    FigureFailure,
    FigureIndex,
    FigureReport,
    FiguresError,
    PageContent,
    Reason,
)
from manuallabor.figures.vector import export_vector
from manuallabor.parse import geometry as g
from manuallabor.parse.pipeline import Emit, stdout_emit
from manuallabor.parse.types import FigureCandidate
from manuallabor.project import DocPaths, ProjectPaths


@dataclass
class Extracted:
    """One extracted figure image, before it is written to disk."""

    method: Extraction
    reason: Reason
    image: Image.Image
    png: bytes | None = None  # verbatim bytes (DOCX PNG); else encode_png(image)
    svg: bytes | None = None
    crop_source: str | None = None
    render_rect: list[float] | None = None
    dpi: float | None = None
    mad: float | None = None
    p99: float | None = None
    source_format: str | None = None
    source_xref: int | None = None
    source_sha256: str | None = None
    bpc: int | None = None


def extract_pdf_figure(
    doc: Any,
    pno: int,
    bbox: list[float],
    *,
    has_text_layer: bool = True,
    pc: PageContent | None = None,
    cache: DecodeCache | None = None,
) -> Extracted:
    """Decide the method for one PDF figure region and extract it (pno is 0-based)."""
    page = doc[pno]
    if pc is None:
        pc = load_page_content(doc, page, has_text_layer=has_text_layer)
    cache = cache or DecodeCache()
    dec: Decision = decide(bbox, pc)
    reason: Reason = dec.reason
    if dec.method == Extraction.native and dec.placement is not None:
        res = extract_native(doc, page, dec.placement)
        if res is not None:
            return Extracted(
                Extraction.native,
                "single_image",
                res.image,
                dpi=effective_dpi(res.image.width, res.image.height, bbox),
                mad=res.mad,
                p99=res.p99,
                source_format=res.source_format,
                source_xref=res.source_xref,
                source_sha256=res.source_sha256,
                bpc=res.bpc,
            )
        reason = "render_disagreement"
    elif dec.method == Extraction.vector:
        svg, img, outer = export_vector(doc, pno, bbox, pc.page_rect)
        return Extracted(
            Extraction.vector,
            "vector_only",
            img,
            svg=svg,
            render_rect=outer,
            dpi=float(RENDER_DPI),
        )
    cr: CropResult = crop_region(doc, pno, page, bbox, pc, cache)
    return Extracted(
        Extraction.crop,
        reason,
        cr.image,
        crop_source=cr.crop_source,
        render_rect=cr.render_rect,
        dpi=cr.effective_dpi,
    )


# --------------------------------------------------------------------------------------------


def _versions() -> dict[str, str]:
    out = {"algo": FIGURES_ALGO_VERSION, "mupdf": str(pymupdf.mupdf_version)}
    for name in ("PyMuPDF", "pillow", "imagehash", "python-docx"):
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "unknown"
    return out


def _file_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _fingerprint(doc: Document, dp: DocPaths) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "versions": _versions(),
                "doc_sha256": doc.sha256,
                "parser_versions": doc.parser_versions,
                "figures_json": _file_sha(dp.figures),
                "blocks_json": _file_sha(dp.blocks),
            }
        )
    )


def _load_report(dp: DocPaths) -> FigureReport | None:
    if not dp.figure_report.is_file():
        return None
    try:
        rep = read_json(dp.figure_report, FigureReport)
    except ValueError:
        return None
    return rep if rep.algo_version == FIGURES_ALGO_VERSION else None


def _report_is_current(paths: ProjectPaths, dp: DocPaths, doc: Document, fp: str) -> bool:
    rep = _load_report(dp)
    if rep is None or rep.fingerprint != fp:
        return False
    for f in rep.figures:
        png = paths.figure_file(doc.slug, f.figure_id, "png")
        if not png.is_file() or _file_sha(png) != f.png_sha256:
            return False
        if f.svg_sha256 is not None:
            svg = paths.figure_file(doc.slug, f.figure_id, "svg")
            if not svg.is_file() or _file_sha(svg) != f.svg_sha256:
                return False
    return True


def _by_method(figs: list[FigureExtraction]) -> dict[str, int]:
    return {m.value: sum(1 for f in figs if f.method == m) for m in Extraction}


def _extract_doc(
    paths: ProjectPaths, doc: Document, dp: DocPaths, blocks: list[Block], fp: str
) -> tuple[FigureReport, list[str]]:
    cands = read_json_list(dp.figures, FigureCandidate)
    cand_by_id = {c.figure_id: c for c in cands}
    fig_blocks = sorted(
        (b for b in blocks if b.type == BlockType.figure and b.figure_id),
        key=lambda b: ids.block_sort_key(str(b.figure_id)),
    )
    block_ids = [str(b.figure_id) for b in fig_blocks]
    if len(set(block_ids)) != len(block_ids) or set(block_ids) != set(cand_by_id):
        missing = sorted(set(block_ids) ^ set(cand_by_id))
        raise FiguresError(f"figure ids differ between blocks.json and figures.json: {missing}")
    captions: dict[str, CaptionMatch] = find_captions(blocks)
    src = paths.source(doc.filename)
    if not src.is_file():
        raise FiguresError(f"source file missing: {src}")
    figs: list[FigureExtraction] = []
    failures: list[FigureFailure] = []
    no_text = set(doc.pages_without_text_layer)
    pdf: Any = None
    docx_imgs: DocxImages | None = None
    cache = DecodeCache()
    pcs: dict[int, PageContent] = {}
    try:
        if doc.kind == DocKind.docx:
            docx_imgs = DocxImages(src)
        else:
            pdf = pymupdf.open(str(src))
        for b in fig_blocks:
            fid = str(b.figure_id)
            cand = cand_by_id[fid]
            try:
                if docx_imgs is not None:
                    ex = _extract_docx(docx_imgs, cand)
                else:
                    if b.bbox is None:
                        raise FiguresError(f"{fid}: PDF figure block without bbox")
                    pno = b.page - 1
                    if pno not in pcs:
                        pcs.clear()
                        pcs[pno] = load_page_content(
                            pdf, pdf[pno], has_text_layer=b.page not in no_text
                        )
                    ex = extract_pdf_figure(pdf, pno, list(b.bbox), pc=pcs[pno], cache=cache)
            except UnsupportedImage as exc:
                failures.append(
                    FigureFailure(figure_id=fid, block_id=b.id, page=b.page, reason=str(exc))
                )
                continue
            png = ex.png if ex.png is not None else encode_png(ex.image)
            write_if_changed(paths.figure_file(doc.slug, fid, "png"), png)
            svg_sha: str | None = None
            if ex.svg is not None:
                write_if_changed(paths.figure_file(doc.slug, fid, "svg"), ex.svg)
                svg_sha = sha256_bytes(ex.svg)
            cap = captions.get(fid)
            area_frac = None
            if b.bbox is not None and pdf is not None:
                pr = pcs[b.page - 1].page_rect
                area_frac = round(g.area(b.bbox) / g.area(pr), 6) if g.area(pr) > 0 else None
            figs.append(
                FigureExtraction(
                    figure_id=fid,
                    block_id=b.id,
                    page=b.page,
                    bbox=b.bbox,
                    method=ex.method,
                    reason=ex.reason,
                    crop_source=ex.crop_source,  # type: ignore[arg-type]
                    source_format=ex.source_format,
                    source_xref=ex.source_xref,
                    source_sha256=ex.source_sha256,
                    bpc=ex.bpc,
                    render_rect=ex.render_rect,
                    png_sha256=sha256_bytes(png),
                    svg_sha256=svg_sha,
                    width=ex.image.width,
                    height=ex.image.height,
                    phash=phash_hex(ex.image),
                    blank=is_blank(ex.image),
                    effective_dpi=ex.dpi,
                    render_mad=ex.mad,
                    render_p99=ex.p99,
                    bbox_area_frac=area_frac,
                    caption_block_id=cap.block_id if cap else None,
                    caption_original=cap.text if cap else None,
                    caption_trimmed=cap.trimmed if cap else False,
                    hint_xrefs=list(cand.image_xrefs),
                    hint_has_drawings=cand.has_drawings,
                )
            )
    finally:
        if pdf is not None:
            pdf.close()
    # stale files: FIG-* files of this document that are not in the current figure set
    keep = {f"{f.figure_id}.png" for f in figs} | {f"{f.figure_id}.json" for f in figs}
    keep |= {f"{f.figure_id}.svg" for f in figs if f.svg_sha256 is not None}
    stale: list[str] = []
    fdir = paths.figure_dir(doc.slug)
    if fdir.is_dir():
        for p in sorted(fdir.iterdir()):
            if p.name.startswith("FIG-") and p.name not in keep:
                p.unlink()
                stale.append(p.name)
    report = FigureReport(
        doc_id=doc.slug,
        fingerprint=fp,
        algo_version=FIGURES_ALGO_VERSION,
        figures=figs,
        failures=failures,
    )
    return report, stale


def _extract_docx(imgs: DocxImages, cand: FigureCandidate) -> Extracted:
    if cand.docx_image_rid is None:
        raise UnsupportedImage("no_image_part")
    r = imgs.extract(cand.docx_image_rid)
    return Extracted(
        Extraction.native,
        "docx_image",
        r.image,
        png=r.png,
        dpi=r.effective_dpi,
        source_format=r.source_format,
        source_sha256=r.source_sha256,
    )


def _process_doc(paths: ProjectPaths, slug: str, force: bool, emit: Emit) -> FigureReport | None:
    t0 = time.monotonic()
    doc = paths.load_document(slug)
    dp = paths.doc(slug)
    if not dp.figures.is_file() or not dp.blocks.is_file():
        raise FiguresError("document is not parsed (blocks.json / parse/figures.json missing)")
    fp = _fingerprint(doc, dp)
    if not force and _report_is_current(paths, dp, doc, fp):
        rep = _load_report(dp)
        assert rep is not None
        emit(
            {
                "doc": slug,
                "stage": "figures",
                "status": "skip",
                "figures": len(rep.figures),
                "by_method": _by_method(rep.figures),
                "failures": len(rep.failures),
                "elapsed_ms": 0,
                "detail": "up to date",
            }
        )
        return rep
    blocks = read_json_list(dp.blocks, Block)
    # drop the old report first so an interrupted run is never mistaken for a finished one
    if dp.figure_report.is_file():
        dp.figure_report.unlink()
    report, stale = _extract_doc(paths, doc, dp, blocks, fp)
    write_if_changed(dp.figure_report, dump_json(report).encode("utf-8"))
    emit(
        {
            "doc": slug,
            "stage": "figures",
            "status": "done",
            "figures": len(report.figures),
            "by_method": _by_method(report.figures),
            "failures": len(report.failures),
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"removed stale: {stale}" if stale else None,
        }
    )
    return report


def _sidecar_phase(
    paths: ProjectPaths, reports: dict[str, FigureReport], entries: dict[str, DedupeEntry]
) -> None:
    for slug in sorted(reports):
        rep = reports[slug]
        doc = paths.load_document(slug)
        for f in rep.figures:
            sc = paths.figure_file(slug, f.figure_id, "json")
            existing: FigureRecord | None = None
            if sc.is_file():
                try:
                    existing = read_json(sc, FigureRecord)
                except ValueError:
                    existing = None
            rec = build_record(f, doc, entries[f.figure_id], existing)
            write_if_changed(sc, dump_json(rec).encode("utf-8"))
            _check_targets(paths, slug, rec)


def _check_targets(paths: ProjectPaths, slug: str, rec: FigureRecord) -> None:
    base = paths.figure_dir(slug)
    for rel in (rec.file, rec.svg):
        if rel is not None and not (base / rel).resolve().is_file():
            raise FiguresError(f"{rec.id}: {rel} does not exist")


def run_figures(
    paths: ProjectPaths,
    *,
    only: str | None = None,
    force: bool = False,
    emit: Emit = stdout_emit,
) -> list[str]:
    """Extract figures for every parsed document. Returns the slugs that failed."""
    pymupdf.TOOLS.set_aa_level(8)
    slugs = paths.list_slugs()
    if only is not None:
        if only not in slugs:
            emit({"doc": only, "stage": "figures", "status": "error", "detail": "unknown document"})
            return [only]
        slugs = [only]
    failed: list[str] = []
    for slug in slugs:
        try:
            _process_doc(paths, slug, force, emit)
        except Exception as exc:
            failed.append(slug)
            emit(
                {
                    "doc": slug,
                    "stage": "figures",
                    "status": "error",
                    "figures": None,
                    "by_method": None,
                    "failures": None,
                    "elapsed_ms": None,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
    # project-wide dedupe over every document that has a finished report
    reports: dict[str, FigureReport] = {}
    for slug in paths.list_slugs():
        if slug in failed:
            continue
        rep = _load_report(paths.doc(slug))
        if rep is not None:
            reports[slug] = rep
    items = [
        DedupeItem(
            figure_id=f.figure_id,
            source_doc=slug,
            method=f.method,
            width=f.width,
            height=f.height,
            png_sha256=f.png_sha256,
            svg_sha256=f.svg_sha256,
            phash=f.phash,
            blank=f.blank,
        )
        for slug, rep in reports.items()
        for f in rep.figures
    ]
    entries = dedupe(items)
    index = FigureIndex(
        algo_version=FIGURES_ALGO_VERSION, near_max_dist=NEAR_DUP_MAX_DIST, entries=entries
    )
    write_if_changed(paths.figures_index, dump_json(index).encode("utf-8"))
    try:
        _sidecar_phase(paths, reports, {e.figure_id: e for e in entries})
    except Exception as exc:
        emit(
            {
                "stage": "figures_dedupe",
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
        raise
    emit(
        {
            "stage": "figures_dedupe",
            "status": "done",
            "exact": sum(1 for e in entries if e.kind == "exact"),
            "near": sum(1 for e in entries if e.kind == "near"),
        }
    )
    return failed
