"""Crop extraction (design section 5): raster sub-crop when possible, else an isolated render."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image

from manuallabor.figures.decide import ink_drawings, relevant_placements, visible_text
from manuallabor.figures.isolate import isolated_page, outer_rect
from manuallabor.figures.native import decode_xref, is_upright
from manuallabor.figures.types import CROP_MARGIN_PT, RENDER_DPI, CropSource, PageContent, Placement
from manuallabor.figures.vector import pixmap_to_image
from manuallabor.parse import geometry as g


@dataclass
class CropResult:
    image: Image.Image
    crop_source: CropSource
    effective_dpi: float
    render_rect: list[float]


class DecodeCache:
    """Keeps the most recently decoded raster (scanned pages decode to tens of MB)."""

    def __init__(self) -> None:
        self._key: tuple[int, int] | None = None
        self._img: Image.Image | None = None

    def get(self, doc: Any, xref: int) -> Image.Image:
        key = (id(doc), xref)
        if self._img is None or self._key != key:
            info = doc.extract_image(xref) or {}
            self._img = decode_xref(doc, xref, int(info.get("smask") or 0))
            self._key = key
        return self._img


def placement_dpi(p: Placement) -> float:
    bw, bh = p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]
    if bw <= 0 or bh <= 0:
        return float(RENDER_DPI)
    return min(p.width / (bw / 72.0), p.height / (bh / 72.0))


def _raster_candidate(region: Sequence[float], pc: PageContent) -> Placement | None:
    rel = relevant_placements(region, pc)
    if len(rel) != 1:
        return None
    p = rel[0]
    ra = g.area(region)
    if ra <= 0 or g.intersection(p.bbox, region) / ra < 0.99:
        return None
    if not is_upright(p.transform):
        return None
    if ink_drawings(region, pc) or visible_text(region, pc):
        return None
    return p


def crop_region(
    doc: Any,
    pno: int,
    page: Any,
    bbox: Sequence[float],
    pc: PageContent,
    cache: DecodeCache,
) -> CropResult:
    outer = outer_rect(pc.page_rect, bbox, CROP_MARGIN_PT)
    p = _raster_candidate(bbox, pc)
    if p is not None:
        x0, y0 = max(outer[0], p.bbox[0]), max(outer[1], p.bbox[1])
        x1, y1 = min(outer[2], p.bbox[2]), min(outer[3], p.bbox[3])
        a, _, _, d, e, f = p.transform
        px0 = max(0, math.floor((x0 - e) / a * p.width - 1e-6))
        px1 = min(p.width, math.ceil((x1 - e) / a * p.width + 1e-6))
        py0 = max(0, math.floor((y0 - f) / d * p.height - 1e-6))
        py1 = min(p.height, math.ceil((y1 - f) / d * p.height + 1e-6))
        if px1 > px0 and py1 > py0:
            img = cache.get(doc, p.xref).crop((px0, py0, px1, py1))
            return CropResult(img, "raster", round(placement_dpi(p), 1), outer)
    rel = relevant_placements(bbox, pc)
    dpi = min([float(RENDER_DPI), *[placement_dpi(r) for r in rel]])
    with isolated_page(doc, pno, outer, keep_images=True, keep_graphics=True) as ip:
        pix = ip.get_pixmap(dpi=RENDER_DPI, alpha=False, annots=False)
        img = pixmap_to_image(pix)
    return CropResult(img, "render", round(dpi, 1), outer)
