"""PyMuPDF on a page without a text layer must account for non-background images."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from manuallabor.contracts.config import ProjectConfig
from manuallabor.parse.pdf_pymupdf import PyMuPdfAdapter
from manuallabor.parse.types import ParseContext
from manuallabor.project import ProjectPaths


def _png(w: int, h: int) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    return pix.tobytes("png")


def test_scanned_page_records_non_background_images(tmp_path: Path) -> None:
    pdf = tmp_path / "s.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=_png(153, 198))  # scan background
    page.insert_image(pymupdf.Rect(100, 100, 300, 260), stream=_png(40, 32))  # photo
    doc.save(str(pdf))
    ctx = ParseContext(
        slug="s",
        sha256="0" * 64,
        page_sizes=((612.0, 792.0),),
        text_layer=(False,),
        config=ProjectConfig(name="t"),
        paths=ProjectPaths(tmp_path),
    )
    out = PyMuPdfAdapter().parse_pdf(pdf, ctx)
    pg = out.pages[0]
    assert pg.blocks == []
    reasons = sorted(s.reason for s in pg.skipped)
    assert reasons == ["scan_background", "scan_page_region"]
    region = next(s for s in pg.skipped if s.reason == "scan_page_region")
    assert region.bbox is not None and region.bbox[0] >= 99
