"""Vector export: isolate by redaction, then MuPDF's own SVG and 300-dpi PNG (design section 4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PIL import Image

from manuallabor.figures.isolate import isolated_page, outer_rect
from manuallabor.figures.types import RENDER_DPI, VECTOR_MARGIN_PT


def pixmap_to_image(pix: Any) -> Image.Image:
    mode = "RGB" if pix.n - pix.alpha == 3 else "L"
    if pix.alpha:
        mode += "A"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples, "raw", mode, pix.stride)


def export_vector(
    src: Any, pno: int, bbox: Sequence[float], page_rect: Sequence[float]
) -> tuple[bytes, Image.Image, list[float]]:
    outer = outer_rect(page_rect, bbox, VECTOR_MARGIN_PT)
    with isolated_page(src, pno, outer, keep_images=False) as page:
        svg = page.get_svg_image(text_as_path=True)
        pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False, annots=False)
        img = pixmap_to_image(pix)
    return svg.encode("utf-8"), img, outer
