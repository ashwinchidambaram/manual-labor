"""The threshold suggestion (design 10 section 4.3). Never applied from here."""

from __future__ import annotations

from collections.abc import Sequence

from manuallabor.calibration.buckets import bucketize, pooled, wilson_hi, wilson_lo
from manuallabor.calibration.types import (
    MIN_SUGGEST_N,
    Outcome,
    ThresholdSuggestion,
)

__all__ = ["suggest_threshold"]

MAX_EXTRA = 100_000


def _extra_needed(k: int, n: int, target: float) -> int | None:
    """How many more zero-edit decisions bring wilson_hi below target (None: never)."""
    if n > 0 and k / n >= target:
        return None
    lo, hi = 0, MAX_EXTRA
    if wilson_hi(k, n + hi) >= target:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if wilson_hi(k, n + mid) < target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def suggest_threshold(
    outs: Sequence[Outcome], target: float, current: float | None = None
) -> tuple[ThresholdSuggestion, list[str]]:
    """The lowest t in [0.50, 0.95] such that the reviewed decisions with score >= t number at
    least MIN_SUGGEST_N, have a Wilson upper bound below the target edit rate, and no
    non-sparse bucket above t has a lower bound above it. Warnings: `current_too_low`."""
    rows = pooled(outs)
    buckets = bucketize(outs)
    warnings: list[str] = []
    if current is not None:
        sel = [o for o in outs if not o.numeric and o.score >= current - 1e-9]
        k = sum(1 for o in sel if o.edited)
        if sel and wilson_lo(k, len(sel)) > target:
            warnings.append(
                f"current_too_low: {k}/{len(sel)} reviewed decisions at or above {current:g} "
                f"were edited (lower bound {wilson_lo(k, len(sel)):.3f} > target {target:g})"
            )
    suggested: float | None = None
    for r in rows:
        if r.n < MIN_SUGGEST_N:
            continue
        bad_bucket = any(
            (not b.sparse) and b.lo >= r.t - 1e-9 and b.wilson_lo > target for b in buckets
        )
        if r.hi < target and not bad_bucket:
            suggested = r.t
            break
    if suggested is not None:
        return ThresholdSuggestion(suggested=suggested, reason="ok"), warnings
    enough = [r for r in rows if r.n >= MIN_SUGGEST_N]
    if not enough:
        have = max((r.n for r in rows), default=0)
        return (
            ThresholdSuggestion(
                reason="insufficient_data",
                detail=f"{have} reviewed decisions at or above 0.50; {MIN_SUGGEST_N} are needed",
            ),
            warnings,
        )
    best = min(enough, key=lambda r: (r.hi, -r.n, r.t))
    need = _extra_needed(best.edited, best.n, target)
    if need is None:
        detail = (
            f"at {best.t:g}: {best.edited}/{best.n} edited; more decisions cannot bring the "
            f"upper bound below {target:g}"
        )
    else:
        detail = (
            f"at {best.t:g}: {best.edited}/{best.n} edited; about {need} more decisions without "
            f"an edit would bring the upper bound below {target:g}"
        )
    return ThresholdSuggestion(reason="target_not_met", detail=detail), warnings
