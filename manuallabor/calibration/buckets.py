"""Wilson intervals, the 20 fixed score buckets and the pooled "score >= t" rows (design 10 4.2).

Unreviewed auto-approved blocks are unknown, never counted as correct; only reviewed outcomes
exist here. Threshold calibration uses non-numeric outcomes only: numeric-spec blocks are
always queued, so the threshold never governs them."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from manuallabor.calibration.types import (
    BUCKET_WIDTH,
    MIN_BUCKET_N,
    SUGGEST_FLOOR,
    WILSON_Z,
    Outcome,
    PooledRow,
)
from manuallabor.contracts._base import round6
from manuallabor.state.models import CalibrationBucket

__all__ = ["bucketize", "pooled", "threshold_grid", "wilson", "wilson_hi", "wilson_lo"]

N_BUCKETS = round(1 / BUCKET_WIDTH)


def wilson(k: int, n: int, z: float = WILSON_Z) -> tuple[float, float]:
    """The Wilson score interval of k successes in n; (0, 1) when n == 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round6(max(0.0, min(1.0, centre - half))), round6(max(0.0, min(1.0, centre + half)))


def wilson_lo(k: int, n: int, z: float = WILSON_Z) -> float:
    return wilson(k, n, z)[0]


def wilson_hi(k: int, n: int, z: float = WILSON_Z) -> float:
    return wilson(k, n, z)[1]


def bucket_index(score: float) -> int:
    return min(int(score * N_BUCKETS + 1e-9), N_BUCKETS - 1)


def bucketize(outs: Iterable[Outcome]) -> list[CalibrationBucket]:
    """Twenty buckets [0, .05) ... [.95, 1.0] over the non-numeric outcomes."""
    n = [0] * N_BUCKETS
    e = [0] * N_BUCKETS
    for o in outs:
        if o.numeric:
            continue
        i = bucket_index(o.score)
        n[i] += 1
        e[i] += int(o.edited)
    rows: list[CalibrationBucket] = []
    for i in range(N_BUCKETS):
        lo, hi = wilson(e[i], n[i])
        rows.append(
            CalibrationBucket(
                lo=round(i * BUCKET_WIDTH, 2),
                hi=round((i + 1) * BUCKET_WIDTH, 2),
                n=n[i],
                edited=e[i],
                edit_rate=None if n[i] == 0 else round6(e[i] / n[i]),
                wilson_lo=lo,
                wilson_hi=hi,
                sparse=n[i] < MIN_BUCKET_N,
            )
        )
    return rows


def threshold_grid() -> list[float]:
    """0.50, 0.55, ... 0.95: the thresholds a suggestion may name."""
    start = round(SUGGEST_FLOOR / BUCKET_WIDTH)
    return [round(i * BUCKET_WIDTH, 2) for i in range(start, N_BUCKETS)]


def pooled(outs: Sequence[Outcome]) -> list[PooledRow]:
    rows: list[PooledRow] = []
    base = [o for o in outs if not o.numeric]
    for t in threshold_grid():
        sel = [o for o in base if o.score >= t - 1e-9]
        k = sum(1 for o in sel if o.edited)
        lo, hi = wilson(k, len(sel))
        rows.append(
            PooledRow(
                t=t,
                n=len(sel),
                edited=k,
                rate=None if not sel else round6(k / len(sel)),
                lo=lo,
                hi=hi,
            )
        )
    return rows
