"""Reduce a PyMuPDF page to the plain data that `decide` reads."""

from __future__ import annotations

from typing import Any

from manuallabor.figures.types import Drawing, PageContent, Placement, Span

Rect4 = tuple[float, float, float, float]


def _rect(r: Any) -> Rect4:
    return (float(r[0]), float(r[1]), float(r[2]), float(r[3]))


def _xref_int(doc: Any, xref: int, key: str) -> int | None:
    kind, val = doc.xref_get_key(xref, key)
    if kind != "xref":
        return None
    try:
        return int(str(val).split()[0])
    except (ValueError, IndexError):
        return None


def _dim(doc: Any, xref: int, key: str) -> int | None:
    kind, val = doc.xref_get_key(xref, key)
    if kind != "int":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _placement(doc: Any, info: dict[str, Any]) -> Placement | None:
    xref = int(info.get("xref") or 0)
    if xref <= 0:
        return None
    stencil = doc.xref_get_key(xref, "ImageMask")[1] == "true"
    smask_dims: tuple[int, int] | None = None
    sx = _xref_int(doc, xref, "SMask")
    if sx is not None:
        sw, sh = _dim(doc, sx, "Width"), _dim(doc, sx, "Height")
        smask_dims = (sw, sh) if sw is not None and sh is not None else (0, 0)
    t = info["transform"]
    return Placement(
        bbox=_rect(info["bbox"]),
        transform=(float(t[0]), float(t[1]), float(t[2]), float(t[3]), float(t[4]), float(t[5])),
        xref=xref,
        width=int(info["width"]),
        height=int(info["height"]),
        stencil=stencil,
        smask_dims=smask_dims,
    )


def load_page_content(doc: Any, page: Any, *, has_text_layer: bool) -> PageContent:
    pc = PageContent(page_rect=_rect(page.rect), has_text_layer=has_text_layer)
    for info in page.get_image_info(xrefs=True):
        p = _placement(doc, info)
        if p is not None:
            pc.placements.append(p)
    for d in page.get_drawings():
        fill = d.get("fill")
        stroke = d.get("color")
        pc.drawings.append(
            Drawing(
                rect=_rect(d["rect"]),
                fill=tuple(float(c) for c in fill) if fill is not None else None,
                stroke=tuple(float(c) for c in stroke) if stroke is not None else None,
                kinds=tuple(str(it[0]) for it in d.get("items", [])),
            )
        )
    if has_text_layer:
        for sp in page.get_texttrace():
            if int(sp.get("type", 0)) == 3:
                continue
            pc.spans.append(Span(bbox=_rect(sp["bbox"])))
    return pc
