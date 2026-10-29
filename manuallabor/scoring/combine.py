"""The combiner: the one place confidence is computed (SPEC 5.3, design 5)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Final

from manuallabor.contracts._base import round6
from manuallabor.contracts.block import Signal
from manuallabor.contracts.enums import SignalName

EXCLUDED_FROM_COMBINER: Final = frozenset({SignalName.has_numeric_spec})


def combine(signals: Iterable[Signal]) -> float | None:
    """min(critical) x geometric mean(soft), clamped to [0, 1] and rounded to 6 places.

    Criticality is the producer's `critical` flag. has_numeric_spec is a rule, not a score, and
    never enters. Missing signals are simply absent. None only when no signal applies."""
    used = [s for s in signals if s.name not in EXCLUDED_FROM_COMBINER]
    if not used:
        return None
    crit = sorted(s.value for s in used if s.critical)
    soft = sorted(s.value for s in used if not s.critical)
    c_min = crit[0] if crit else 1.0
    if not soft:
        g = 1.0
    elif 0.0 in soft:
        g = 0.0
    else:
        g = math.exp(math.fsum(math.log(v) for v in soft) / len(soft))
    return round6(min(1.0, max(0.0, c_min * g)))
