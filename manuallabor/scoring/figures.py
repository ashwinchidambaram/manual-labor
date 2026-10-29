"""figure_method, figure_resolution, figure_attach_rule (design 2.9)."""

from __future__ import annotations

from manuallabor.contracts.block import Signal
from manuallabor.contracts.enums import AttachRule, SignalName
from manuallabor.scoring.types import (
    ATTACH,
    FIG_BASE,
    FIG_CAP,
    FIG_DPI_FULL,
    FIG_SMALL_FRAC,
    FIG_SMALL_PT,
    FigureInputs,
    clamp01,
    truncate,
)


def figure_method(fi: FigureInputs) -> Signal:
    if fi.extraction is None:
        reason = fi.failure.reason if fi.failure is not None else "no extraction"
        return Signal(
            name=SignalName.figure_method,
            value=0.0,
            critical=True,
            detail=truncate(f"extraction failed: {reason}"),
        )
    ex = fi.extraction
    value = FIG_BASE[ex.method]
    parts = [f"{ex.method.value} ({ex.reason})"]
    if fi.dedupe is not None and fi.dedupe.kind == "near":
        value = min(value, FIG_CAP)
        parts.append(f"near-duplicate of {fi.dedupe.duplicate_of} (d={fi.dedupe.distance})")
    small = False
    if ex.bbox is not None:
        x0, y0, x1, y1 = ex.bbox
        small = min(x1 - x0, y1 - y0) < FIG_SMALL_PT
    if ex.bbox_area_frac is not None and ex.bbox_area_frac < FIG_SMALL_FRAC:
        small = True
    if small:
        value = min(value, FIG_CAP)
        parts.append("small region")
    return Signal(
        name=SignalName.figure_method,
        value=clamp01(value),
        critical=True,
        detail=truncate("; ".join(parts)),
    )


def figure_resolution(fi: FigureInputs) -> Signal | None:
    if fi.extraction is None or fi.extraction.effective_dpi is None:
        return None
    dpi = fi.extraction.effective_dpi
    return Signal(
        name=SignalName.figure_resolution,
        value=clamp01(dpi / FIG_DPI_FULL),
        critical=False,
        detail=f"{dpi:.0f} dpi effective",
    )


def figure_attach_rule(fi: FigureInputs) -> Signal | None:
    """Omitted until attachment has run (module 5 fills attach_rule / articles)."""
    if fi.attach_rule == AttachRule.none and not fi.articles:
        return None
    return Signal(
        name=SignalName.figure_attach_rule,
        value=ATTACH[fi.attach_rule],
        critical=False,
        detail=f"attached by {fi.attach_rule.value}",
    )
