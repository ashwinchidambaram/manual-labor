"""Isolated one-page documents: everything outside a rectangle is redacted (design section 4)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from manuallabor.figures.mu import pymupdf
from manuallabor.parse import geometry as g


def outer_rect(page_rect: Sequence[float], bbox: Sequence[float], margin: float) -> list[float]:
    """(qbox(bbox) + margin) clipped to the page, rounded to 3 dp."""
    r = g.qbox(bbox)
    return g.qbox(
        [
            max(page_rect[0], r[0] - margin),
            max(page_rect[1], r[1] - margin),
            min(page_rect[2], r[2] + margin),
            min(page_rect[3], r[3] + margin),
        ]
    )


def clamp_bbox(page_rect: Sequence[float], bbox: Sequence[float]) -> list[float] | None:
    """`bbox` intersected with the page; None when the result is degenerate (a side < 1 pt)."""
    r = g.qbox(bbox)
    c = [
        max(page_rect[0], r[0]),
        max(page_rect[1], r[1]),
        min(page_rect[2], r[2]),
        min(page_rect[3], r[3]),
    ]
    if c[2] - c[0] < 1.0 or c[3] - c[1] < 1.0:
        return None
    return g.qbox(c)


@contextmanager
def isolated_page(
    src: Any, pno: int, outer: Sequence[float], *, keep_images: bool, keep_graphics: bool = False
) -> Iterator[Any]:
    """Yield a temporary in-memory page cropped to `outer` with outside content redacted.

    The source document is never modified. Strips are added in a fixed order (top, bottom,
    left, right) so the result is deterministic.
    """
    tmp = pymupdf.open()
    try:
        tmp.insert_pdf(src, from_page=pno, to_page=pno, annots=False, links=False, widgets=False)
        page = tmp[0]
        pr = page.rect
        strips = [
            (pr.x0, pr.y0, pr.x1, outer[1]),
            (pr.x0, outer[3], pr.x1, pr.y1),
            (pr.x0, outer[1], outer[0], outer[3]),
            (outer[2], outer[1], pr.x1, outer[3]),
        ]
        n = 0
        for s in strips:
            if s[2] - s[0] > 1e-3 and s[3] - s[1] > 1e-3:
                page.add_redact_annot(pymupdf.Rect(*s), fill=False)
                n += 1
        if n:
            page.apply_redactions(
                images=(
                    pymupdf.PDF_REDACT_IMAGE_NONE
                    if keep_images
                    else pymupdf.PDF_REDACT_IMAGE_REMOVE
                ),
                graphics=(
                    pymupdf.PDF_REDACT_LINE_ART_NONE
                    if keep_graphics
                    else pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
                ),
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        page.set_cropbox(pymupdf.Rect(*outer))
        yield page
    finally:
        tmp.close()
