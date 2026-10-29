"""Test 10: the combiner."""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from manuallabor.contracts.block import Signal
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.combine import EXCLUDED_FROM_COMBINER, combine

NAMES = [n for n in SignalName if n not in EXCLUDED_FROM_COMBINER]


def sig(name: SignalName, value: float, critical: bool = False) -> Signal:
    return Signal(name=name, value=value, critical=critical)


def test_worked_examples() -> None:
    assert combine([]) is None
    assert combine([sig(SignalName.has_numeric_spec, 0.0)]) is None
    assert combine([sig(SignalName.faithfulness, 1.0, True)]) == 1.0
    s = [
        sig(SignalName.faithfulness, 1.0, True),
        sig(SignalName.parser_agreement, 0.5, True),
        sig(SignalName.reading_order_risk, 0.9),
        sig(SignalName.garbage_ratio, 1.0),
    ]
    assert combine(s) == round(0.5 * math.sqrt(0.9), 6)
    # a soft zero floors the product; has_numeric_spec (0.0) is ignored
    assert (
        combine([sig(SignalName.garbage_ratio, 0.0), sig(SignalName.faithfulness, 1.0, True)])
        == 0.0
    )
    assert (
        combine([sig(SignalName.has_numeric_spec, 0.0), sig(SignalName.faithfulness, 1.0, True)])
        == 1.0
    )
    # only soft
    assert (
        combine([sig(SignalName.garbage_ratio, 0.81), sig(SignalName.reading_order_risk, 1.0)])
        == 0.9
    )
    # rounding to 6 places
    v = combine([sig(SignalName.garbage_ratio, 1 / 3)])
    assert v == round(1 / 3, 6)


signal_st = st.builds(
    sig,
    st.sampled_from(NAMES),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    st.booleans(),
)
signals_st = st.lists(signal_st, min_size=1, max_size=8, unique_by=lambda s: s.name)


@given(signals_st)
def test_range_and_min_critical(ss: list[Signal]) -> None:
    c = combine(ss)
    assert c is not None and 0.0 <= c <= 1.0
    crit = [s.value for s in ss if s.critical]
    if crit:
        assert c <= min(crit) + 1e-6
    assert c == round(c, 6)


@given(signals_st, st.randoms(use_true_random=False))
def test_permutation_invariant(ss: list[Signal], rnd) -> None:  # type: ignore[no-untyped-def]
    shuffled = list(ss)
    rnd.shuffle(shuffled)
    assert combine(ss) == combine(shuffled)


@given(signals_st, st.integers(min_value=0, max_value=7), st.floats(min_value=0.0, max_value=1.0))
def test_monotone_per_value(ss: list[Signal], idx: int, new: float) -> None:
    i = idx % len(ss)
    old = ss[i]
    if new < old.value:
        return
    up = list(ss)
    up[i] = sig(old.name, new, old.critical)
    a, b = combine(ss), combine(up)
    assert a is not None and b is not None and b >= a - 1e-6


@given(signals_st, st.floats(min_value=0.0, max_value=1.0), st.booleans())
def test_numeric_spec_ignored(ss: list[Signal], v: float, crit: bool) -> None:
    ss = [s for s in ss if s.name != SignalName.has_numeric_spec]
    if not ss:
        return
    assert combine(ss) == combine([*ss, sig(SignalName.has_numeric_spec, v, crit)])
