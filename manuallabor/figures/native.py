"""Native raster extraction: decode with MuPDF, verify against the page render (design 3)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from manuallabor.figures.encode import composite_on_white, normalize_mode, sha256_bytes
from manuallabor.figures.mu import pymupdf
from manuallabor.figures.types import RENDER_MAD_MAX, RENDER_P99_MAX, RENDER_SIDE, Placement
from manuallabor.figures.vector import pixmap_to_image


@dataclass
class NativeResult:
    image: Image.Image
    mad: float
    p99: float
    source_format: str | None
    source_xref: int
    bpc: int | None
    source_sha256: str | None


def decode_xref(doc: Any, xref: int, smask: int = 0) -> Image.Image:
    """Decode an image XObject to Pillow pixels (L/RGB, plus alpha from its soft mask)."""
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.colorspace is None or pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    img = pixmap_to_image(pix)
    if smask > 0:
        mp = pymupdf.Pixmap(doc, smask)
        if mp.alpha:
            mp = pymupdf.Pixmap(mp, 0)
        if mp.colorspace is None or mp.colorspace.n != 1:
            mp = pymupdf.Pixmap(pymupdf.csGRAY, mp)
        mask = pixmap_to_image(mp)
        if mask.size == img.size:
            img = img.convert("LA" if img.mode == "L" else "RGBA")
            img.putalpha(mask)
    return img


def _to_small_gray(img: Image.Image, size: tuple[int, int]) -> np.ndarray[Any, Any]:
    g = composite_on_white(img).convert("L").resize(size, Image.Resampling.LANCZOS)
    return np.asarray(g, dtype=np.int16)


def agreement(render: Image.Image, img: Image.Image) -> tuple[float, float]:
    """(MAD, p99) between the page render and our decoded image, both at 64 px long side."""
    rw, rh = render.size
    scale = RENDER_SIDE / max(rw, rh)
    size = (max(1, round(rw * scale)), max(1, round(rh * scale)))
    a = _to_small_gray(render, size)
    b = _to_small_gray(img, size)
    diff = np.abs(a - b)
    return round(float(diff.mean()), 3), round(float(np.percentile(diff, 99)), 3)


def render_region(page: Any, rect: Sequence[float], dpi: int = 72) -> Image.Image:
    pix = page.get_pixmap(clip=pymupdf.Rect(*rect), dpi=dpi, alpha=False, annots=False)
    return pixmap_to_image(pix)


def is_upright(t: Sequence[float]) -> bool:
    return t[0] > 0 and t[3] > 0 and abs(t[1]) <= 1e-6 and abs(t[2]) <= 1e-6


def _passes(mad: float, p99: float) -> bool:
    return mad <= RENDER_MAD_MAX and p99 <= RENDER_P99_MAX


def extract_native(doc: Any, page: Any, placement: Placement) -> NativeResult | None:
    """Decode the placement's image and orient it. None means the render check failed."""
    info = doc.extract_image(placement.xref) or {}
    img = decode_xref(doc, placement.xref, int(info.get("smask") or 0))
    pr = page.rect
    rect = (
        max(pr.x0, placement.bbox[0]),
        max(pr.y0, placement.bbox[1]),
        min(pr.x1, placement.bbox[2]),
        min(pr.y1, placement.bbox[3]),
    )
    if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
        return None
    render = render_region(page, rect)
    chosen: tuple[Image.Image, float, float] | None = None
    if is_upright(placement.transform):
        mad, p99 = agreement(render, img)
        if _passes(mad, p99):
            chosen = (img, mad, p99)
    else:
        best: tuple[float, float, Image.Image] | None = None
        for op in Image.Transpose:  # enum order: the first minimum wins
            cand = img.transpose(op)
            mad, p99 = agreement(render, cand)
            if _passes(mad, p99) and (best is None or mad < best[0]):
                best = (mad, p99, cand)
        if best is not None:
            chosen = (best[2], best[0], best[1])
    if chosen is None:
        return None
    out, mad, p99 = chosen
    raw = info.get("image")
    return NativeResult(
        image=normalize_mode(out),
        mad=mad,
        p99=p99,
        source_format=info.get("ext"),
        source_xref=placement.xref,
        bpc=info.get("bpc"),
        source_sha256=sha256_bytes(bytes(raw)) if isinstance(raw, (bytes, bytearray)) else None,
    )


def effective_dpi(width: int, height: int, region: Sequence[float]) -> float | None:
    w_in = (region[2] - region[0]) / 72.0
    h_in = (region[3] - region[1]) / 72.0
    if w_in <= 0 or h_in <= 0:
        return None
    v = min(width / w_in, height / h_in)
    return None if not math.isfinite(v) else round(v, 1)
