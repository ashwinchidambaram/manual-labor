"""Method decision (design section 2). Pure: reads only PageContent."""

from __future__ import annotations

from collections.abc import Sequence

from manuallabor.contracts.enums import Extraction
from manuallabor.figures.types import (
    EPS,
    INSIDE_MIN,
    NATIVE_COVER,
    REL_COVER,
    REL_INSIDE,
    VECTOR_MARGIN_PT,
    Decision,
    Drawing,
    PageContent,
    Placement,
    Reason,
    Span,
)
from manuallabor.parse import geometry as g

Box = Sequence[float]


def _overlaps(a: Box, b: Box) -> bool:
    """Strict overlap that also holds for zero-width/height boxes (lines) inside b."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _shrink(b: Box, d: float) -> list[float]:
    return [b[0] + d, b[1] + d, b[2] - d, b[3] - d]


def relevant_placements(region: Box, pc: PageContent) -> list[Placement]:
    out: list[Placement] = []
    ra = g.area(region)
    for p in pc.placements:
        inter = g.intersection(p.bbox, region)
        pa = g.area(p.bbox)
        inside = inter / pa if pa > 0 else 0.0
        if (ra > 0 and inter >= REL_COVER * ra) or inside >= REL_INSIDE:
            out.append(p)
    return out


def _is_frame(d: Drawing, target: Box) -> bool:
    if d.fill is not None or d.stroke is None:
        return False
    if g.area(d.rect) < 0.9 * g.area(target):
        return False
    if any(abs(d.rect[i] - target[i]) > 2.0 for i in range(4)):
        return False
    if not d.kinds:
        return False
    return all(k == "re" for k in d.kinds) or (len(d.kinds) <= 4 and all(k == "l" for k in d.kinds))


def _is_background(d: Drawing, region: Box) -> bool:
    if d.stroke is not None or d.fill is None:
        return False
    if not all(c >= 0.98 for c in d.fill):
        return False
    return (
        d.rect[0] <= region[0]
        and d.rect[1] <= region[1]
        and d.rect[2] >= region[2]
        and (d.rect[3] >= region[3])
    )


def ink_drawings(region: Box, pc: PageContent, frame_target: Box | None = None) -> list[Drawing]:
    """Drawings that count as figure ink inside `region` (design section 2 definitions)."""
    inner = _shrink(region, 1.0)
    page_area = g.area(pc.page_rect)
    out: list[Drawing] = []
    for d in pc.drawings:
        if not _overlaps(d.rect, inner):
            continue
        if frame_target is not None and _is_frame(d, frame_target):
            continue
        if _is_background(d, region):
            continue
        if page_area > 0 and g.area(d.rect) >= 0.5 * page_area:
            continue
        out.append(d)
    return out


def visible_text(region: Box, pc: PageContent) -> list[Span]:
    inner = _shrink(region, 1.0)
    out: list[Span] = []
    for s in pc.spans:
        sa = g.area(s.bbox)
        if sa <= 0:
            continue
        if g.intersection(s.bbox, inner) >= 0.5 * sa:
            out.append(s)
    return out


def _axis_aligned(t: Sequence[float]) -> bool:
    a, b, c, d = t[0], t[1], t[2], t[3]
    return (abs(b) <= 1e-6 and abs(c) <= 1e-6) or (abs(a) <= 1e-6 and abs(d) <= 1e-6)


def _one(
    method: Extraction, reason: Reason, p: Placement, cover: float, n_ink: int = 0
) -> Decision:
    return Decision(method, reason, p, 1, n_ink, cover)


def decide(region: Box | None, pc: PageContent) -> Decision:
    """Pick the extraction method for one figure region. Rule 12 still needs the render check."""
    if region is None:
        return Decision(Extraction.native, "docx_image")
    if not pc.has_text_layer:
        return Decision(Extraction.crop, "scanned_page")
    rel = relevant_placements(region, pc)
    if not rel:
        ink = ink_drawings(region, pc)
        if not ink:
            return Decision(Extraction.crop, "no_content")
        outer = g.expand(region, VECTOR_MARGIN_PT + EPS)
        if all(
            d.rect[0] >= outer[0]
            and d.rect[1] >= outer[1]
            and d.rect[2] <= outer[2]
            and d.rect[3] <= outer[3]
            for d in ink
        ):
            return Decision(Extraction.vector, "vector_only", n_ink=len(ink))
        return Decision(Extraction.crop, "vector_crossing_paths", n_ink=len(ink))
    if len(rel) >= 2:
        return Decision(Extraction.crop, "multiple_images", n_relevant=len(rel))
    p = rel[0]
    ra, pa = g.area(region), g.area(p.bbox)
    inter = g.intersection(p.bbox, region)
    cover = inter / ra if ra > 0 else 0.0
    inside = inter / pa if pa > 0 else 0.0
    if cover < NATIVE_COVER or inside < INSIDE_MIN:
        return _one(Extraction.crop, "image_partial_cover", p, cover)
    ink = [
        d
        for d in ink_drawings(region, pc, frame_target=p.bbox)
        if _overlaps(d.rect, _shrink(p.bbox, 0.0))
    ]
    if ink:
        return _one(Extraction.crop, "image_with_drawings", p, cover, len(ink))
    if visible_text(p.bbox, pc):
        return _one(Extraction.crop, "image_with_text", p, cover)
    if not _axis_aligned(p.transform):
        return _one(Extraction.crop, "image_transform", p, cover)
    if p.stencil:
        return _one(Extraction.crop, "stencil_mask", p, cover)
    if p.smask_dims is not None and p.smask_dims != (p.width, p.height):
        return _one(Extraction.crop, "smask_size", p, cover)
    return _one(Extraction.native, "single_image", p, cover)
