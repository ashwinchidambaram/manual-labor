"""The threshold suggestion (design 10 section 4.3). Never applied from here."""

from __future__ import annotations

from collections.abc import Sequence

from manuallabor.calibration.buckets import bucketize, pooled, wilson_hi, wilson_lo
from manuallabor.calibration.types import (
    MIN_BUCKET_N,
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
    least MIN_SUGGEST_N, have a Wilson upper bound below the target edit rate, and no bucket
    at or above t (sparse or not) has a Wilson lower bound above the target.

    No extrapolation: t is never below the lowest bucket that holds MIN_BUCKET_N decisions
    (the scores below it were not observed in any number, so nothing says they are safe), and
    a sparse bucket whose edits are significant (lower bound above the target) blocks every
    t below it however many clean decisions sit lower down. Every bucket from t up to the
    highest observed score must hold MIN_BUCKET_N decisions: a pooled row never jumps an
    unreviewed gap. Warnings: `current_too_low`."""
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
    populated = [b.lo for b in buckets if not b.sparse]
    floor = min(populated) if populated else None
    seen = [i for i, b in enumerate(buckets) if b.n > 0]
    top = seen[-1] if seen else -1

    def gaps(t: float) -> list[float]:
        """Sparse buckets between t and the highest observed score: an unreviewed gap."""
        return [b.lo for b in buckets[: top + 1] if b.lo >= t - 1e-9 and b.sparse]

    gapped: tuple[float, list[float]] | None = None
    for r in rows:
        if r.n < MIN_SUGGEST_N or floor is None or r.t < floor - 1e-9:
            continue
        bad_bucket = any(b.n > 0 and b.lo >= r.t - 1e-9 and b.wilson_lo > target for b in buckets)
        if r.hi < target and not bad_bucket:
            g = gaps(r.t)
            if g:
                gapped = gapped or (r.t, g)
                continue
            suggested = r.t
            break
    if suggested is not None:
        return ThresholdSuggestion(suggested=suggested, reason="ok"), warnings
    if gapped is not None:
        t, g = gapped
        return (
            ThresholdSuggestion(
                reason="insufficient_data",
                detail=f"at {t:g} the buckets starting {', '.join(f'{x:g}' for x in g[:5])} "
                f"hold fewer than {MIN_BUCKET_N} reviewed decisions each; no threshold may "
                "span an unreviewed score range",
            ),
            warnings,
        )
    if floor is None:
        return (
            ThresholdSuggestion(
                reason="insufficient_data",
                detail=f"no score bucket holds {MIN_BUCKET_N} reviewed decisions yet",
            ),
            warnings,
        )
    enough = [r for r in rows if r.n >= MIN_SUGGEST_N and r.t >= floor - 1e-9]
    if not enough:
        have = max((r.n for r in rows if r.t >= floor - 1e-9), default=0)
        return (
            ThresholdSuggestion(
                reason="insufficient_data",
                detail=f"{have} reviewed decisions at or above {max(floor, rows[0].t):g}; "
                f"{MIN_SUGGEST_N} are needed",
            ),
            warnings,
        )
    best = min(enough, key=lambda r: (r.hi, -r.n, r.t))
    need = _extra_needed(best.edited, best.n, target)
    bad = [b for b in buckets if b.n > 0 and b.wilson_lo > target and b.lo >= best.t - 1e-9]
    if best.hi < target and bad:
        b = bad[-1]
        detail = (
            f"at {best.t:g}: {best.edited}/{best.n} edited, but the bucket "
            f"[{b.lo:g}, {b.hi:g}) has {b.edited}/{b.n} edited (lower bound "
            f"{b.wilson_lo:.3f} > {target:g}); no threshold at or below it is safe"
        )
    elif need is None:
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
