"""Per-signal reliability and critical-promotion suggestions (design 10 section 4.5).

A promotion can only lower confidence: scoring takes the promoted signals only when they give a
lower confidence than the baseline combiner (scoring.pipeline.score_block)."""

from __future__ import annotations

from collections.abc import Sequence

from manuallabor.calibration.buckets import wilson
from manuallabor.calibration.types import (
    MIN_SIGNAL_N,
    PROMOTE_MIN_RATE,
    PROMOTE_MIN_SOFT_FRAC,
    SIGNAL_CUTS,
    SIGNAL_SIDE_MIN,
    SIGNAL_UNINFORMATIVE_MIN,
    CriticalPromotion,
    Outcome,
    SignalReliability,
)
from manuallabor.contracts._base import round6

__all__ = ["promotions", "signal_reliability"]

SKIP = frozenset({"has_numeric_spec"})


def _rate(k: int, n: int) -> float | None:
    return None if n == 0 else round6(k / n)


def signal_reliability(outs: Sequence[Outcome], target: float = 0.02) -> list[SignalReliability]:
    names = sorted({n for o in outs for n, _v, _c in o.signals} - SKIP)
    rows: list[SignalReliability] = []
    for name in names:
        obs = [(v, c, o.edited) for o in outs for n, v, c in o.signals if n == name]
        if len(obs) < MIN_SIGNAL_N:
            continue
        cand: list[SignalReliability] = []
        for cut in SIGNAL_CUTS:
            below = [(c, e) for v, c, e in obs if v < cut]
            above = [e for v, _c, e in obs if v >= cut]
            kb, ka = sum(e for _c, e in below), sum(above)
            lob, hib = wilson(kb, len(below))
            loa, hia = wilson(ka, len(above))
            rb, ra = _rate(kb, len(below)), _rate(ka, len(above))
            soft = round6(sum(1 for c, _e in below if not c) / len(below)) if below else 0.0
            klass = "insufficient"
            if len(below) >= SIGNAL_SIDE_MIN and len(above) >= SIGNAL_SIDE_MIN and lob > hia:
                klass = "predictive"
            elif (
                len(below) >= SIGNAL_UNINFORMATIVE_MIN
                and len(above) >= SIGNAL_UNINFORMATIVE_MIN
                and lob <= hia
                and loa <= hib
                and rb is not None
                and ra is not None
                and abs(rb - ra) < target
            ):
                klass = "uninformative"
            cand.append(
                SignalReliability(
                    signal=name,
                    cut=cut,
                    n_below=len(below),
                    edited_below=kb,
                    rate_below=rb,
                    lo_below=lob,
                    hi_below=hib,
                    n_above=len(above),
                    edited_above=ka,
                    rate_above=ra,
                    lo_above=loa,
                    hi_above=hia,
                    klass=klass,  # type: ignore[arg-type]
                    soft_fraction_below=soft,
                )
            )
        best: SignalReliability | None = None
        for r in cand:
            ok = (
                r.klass == "predictive"
                and r.soft_fraction_below >= PROMOTE_MIN_SOFT_FRAC
                and (r.rate_below or 0.0) >= PROMOTE_MIN_RATE
            )
            if ok and (best is None or r.lo_below - r.hi_above > best.lo_below - best.hi_above):
                best = r
        rows.extend(r.model_copy(update={"promote": r is best}) for r in cand)
    return rows


def promotions(rows: Sequence[SignalReliability]) -> list[CriticalPromotion]:
    return [
        CriticalPromotion(
            id=f"promo-{r.signal}-{round(r.cut * 100)}",
            signal=r.signal,
            below=r.cut,
            support=r.n_below,
            rate_below=r.rate_below or 0.0,
            rate_above=r.rate_above or 0.0,
        )
        for r in rows
        if r.promote
    ]
