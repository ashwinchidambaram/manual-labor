"""Design 10 tests 20-22: Wilson, outcomes, signal reliability (pure)."""

from __future__ import annotations

import random

from manuallabor.calibration.buckets import bucketize, pooled, wilson, wilson_hi
from manuallabor.calibration.outcomes import outcomes
from manuallabor.calibration.signals import promotions, signal_reliability
from manuallabor.calibration.suggest import suggest_threshold
from manuallabor.calibration.types import Outcome
from manuallabor.contracts.block import Signal
from manuallabor.scoring.combine import combine
from manuallabor.state.models import ActionKind
from tests.calibration.helpers import example, record


def out(score: float, edited: bool, *, numeric: bool = False, sigs=(), i: int = 0) -> Outcome:  # type: ignore[no-untyped-def]
    return Outcome(
        f"b-clean-p001-{i % 99 + 1:02d}",
        str(i),
        i,
        score,
        numeric,
        "paragraph",
        "born_digital_pdf",
        edited,
        "human",
        "baseline",
        tuple(sigs),
    )


def many(spec: list[tuple[float, int, int]]) -> list[Outcome]:
    rows: list[Outcome] = []
    for score, n, edits in spec:
        for k in range(n):
            rows.append(out(score, k < edits, i=len(rows)))
    return rows


def test_20_wilson() -> None:
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson_hi(0, 133) < 0.02 <= wilson_hi(0, 132)
    assert abs(wilson_hi(1, 190) - 0.0232) < 5e-4
    assert abs(wilson_hi(0, 160) - 0.0166) < 5e-4
    lo, hi = wilson(5, 10)
    assert 0 < lo < 0.5 < hi < 1


def test_20_suggestion_rules() -> None:
    s, _w = suggest_threshold(many([(0.9, 49, 0)]), 0.02)
    assert s.reason == "insufficient_data" and s.suggested is None
    # never below the lowest bucket that holds >= 20 decisions (no extrapolation down to 0.50)
    s, _w = suggest_threshold(many([(0.9, 200, 0)]), 0.02)
    assert (s.reason, s.suggested) == ("ok", 0.9)
    # not enough zero-edit evidence at the target: the price in decisions is stated
    s, _w = suggest_threshold(many([(0.9, 100, 0)]), 0.02)
    assert s.reason == "target_not_met" and "more decisions" in (s.detail or "")
    # a bad, non-sparse bucket above t blocks t
    rows = many([(0.6, 200, 0), (0.97, 30, 15)])
    s, _w = suggest_threshold(rows, 0.02)
    assert s.suggested is None
    # warning when the current threshold is demonstrably too low
    rows = many([(0.9, 100, 30)])
    _s, w = suggest_threshold(rows, 0.02, 0.85)
    assert w and w[0].startswith("current_too_low")


def test_20_numeric_outcomes_are_excluded() -> None:
    rows = [out(0.9, True, numeric=True, i=i) for i in range(5)] + many([(0.9, 10, 0)])
    assert sum(b.n for b in bucketize(rows)) == 10
    assert pooled(rows)[0].n == 10


def test_21_outcome_extraction() -> None:
    acts = [
        record(1, ActionKind.approve, example("b-clean-p001-01", "aa", score=0.9)),
        record(
            2, ActionKind.edit, example("b-clean-p001-02", "bb", shown="bb", final="bb")
        ),  # no-op
        record(3, ActionKind.edit, example("b-clean-p001-03", "cc", shown="cc", final="cd")),
        record(4, ActionKind.skip, example("b-clean-p001-04", "dd")),
        record(5, ActionKind.flag, example("b-clean-p001-05", "ee", flag_category="wrong_text")),
        record(
            6, ActionKind.flag, example("b-clean-p001-06", "ff", flag_category="missing_figure")
        ),
        record(
            7, ActionKind.flag, example("b-clean-p001-07", "gg", flag_category="wrong_grouping")
        ),
        record(8, ActionKind.edit, example("b-clean-p001-08", "hh", numeric=True, final="hx")),
        record(9, ActionKind.edit, example("b-clean-p001-09", "ii", score=None, final="ix")),
        record(
            10,
            ActionKind.proposal_accept,
            example("b-clean-p001-10", "jj", final="jk", proposal={"kind": "text"}),
        ),
        record(
            11,
            ActionKind.proposal_accept,
            example("b-clean-p001-11", "kk", final="kl", proposal={"kind": "attach"}),
        ),
        # latest per (block, raw): approve, then a later edit of the same text
        record(12, ActionKind.approve, example("b-clean-p001-12", "ll")),
        record(13, ActionKind.edit, example("b-clean-p001-12", "ll", final="lx")),
        # the same block with other raw text keeps both observations
        record(14, ActionKind.approve, example("b-clean-p001-12", "mm")),
    ]
    by = {o.action_id: o for o in outcomes(acts)}
    assert set(by) == {1, 2, 3, 5, 8, 10, 13, 14}
    assert not by[1].edited and not by[2].edited and by[3].edited and by[5].edited
    assert by[8].numeric and by[10].source == "agent" and by[10].edited
    assert by[13].edited


def sig(name: str, v: float, critical: bool = False) -> tuple[str, float, bool]:
    return (name, v, critical)


def test_22_signal_reliability_and_promotion() -> None:
    rnd = random.Random(7)
    rows: list[Outcome] = []
    for i in range(100):  # garbage_ratio < 0.8: 40 % edited
        rows.append(
            out(
                0.9,
                i < 40,
                sigs=[sig("garbage_ratio", 0.7), sig("noise", rnd.random())],
                i=len(rows),
            )
        )
    for i in range(200):  # >= 0.8: 2 % edited
        rows.append(
            out(
                0.9,
                i < 4,
                sigs=[sig("garbage_ratio", 0.95), sig("noise", rnd.random())],
                i=len(rows),
            )
        )
    rel = signal_reliability(rows)
    g = [r for r in rel if r.signal == "garbage_ratio"]
    assert any(r.klass == "predictive" and r.cut == 0.8 and r.promote for r in g)
    promo = promotions(rel)
    assert [(p.signal, p.below) for p in promo] == [("garbage_ratio", 0.8)]
    noise = [r for r in rel if r.signal == "noise"]
    assert noise and all(r.klass != "predictive" for r in noise)


def test_22_promotion_never_raises_confidence() -> None:
    """The promoted signals are used only when they lower confidence (scoring takes the min)."""
    from manuallabor.calibration.types import CriticalPromotion
    from manuallabor.contracts.enums import SignalName
    from manuallabor.scoring.learned import promote

    promo = [
        CriticalPromotion(
            id="p", signal="garbage_ratio", below=0.8, support=1, rate_below=0.4, rate_above=0.0
        )
    ]
    rnd = random.Random(3)
    worse = 0
    for _ in range(300):
        sigs = [
            Signal(
                name=SignalName.garbage_ratio,
                value=rnd.choice([0.1, 0.5, 0.7, 0.9]),
                critical=False,
            ),
            Signal(
                name=SignalName.parser_agreement,
                value=rnd.choice([0.3, 0.9, 1.0]),
                critical=rnd.random() < 0.5,
            ),
            Signal(
                name=SignalName.reading_order_risk, value=rnd.choice([0.6, 1.0]), critical=False
            ),
        ]
        base = combine(sigs)
        p2 = combine(promote(sigs, promo))
        assert base is not None and p2 is not None
        taken = min(base, p2)
        assert taken <= base
        worse += p2 > base  # the raw promoted combiner CAN raise; scoring must not take it
    assert worse > 0


def test_22_promotion_never_raises_score_block_confidence() -> None:
    """The real scorer on 1,000 random blocks (so random signal sets: reader agreement,
    garbage, look-alikes, numbers, clean or not) with random promotions: the learned layer may
    lower confidence and queue more, never raise confidence or release a queued block."""
    from manuallabor.calibration.types import CriticalPromotion
    from manuallabor.scoring.learned import LearnedScoring
    from manuallabor.scoring.pipeline import score_block
    from tests.conftest import ctx, make_block

    rng = random.Random(11)
    words = [
        "Torque",
        "the",
        "bolt",
        "to",
        "35",
        "N·m",
        "3S",
        "witha",
        "clean",
        "cloth",
        "§",
        "~~",
        "###",
        "0.5",
        "mm",
        "Check",
        "valve",
        "l0",
        "B8",
        "��",
        "a",
        "b",
    ]
    names = [
        "garbage_ratio",
        "parser_agreement",
        "reading_order_risk",
        "ocr_confidence",
        "textlayer_vs_ocr",
        "llm_verifier",
        "faithfulness",
        "table_consistency",
    ]
    lowered = scored = 0
    signal_sets: set[tuple[str, ...]] = set()
    for _ in range(1000):
        raw = " ".join(rng.choice(words) for _ in range(rng.randint(2, 10)))
        alt = " ".join(w if rng.random() < 0.8 else rng.choice(words) for w in raw.split())
        texts = {"pymupdf": raw}
        if rng.random() < 0.8:
            texts["docling"] = alt
        if rng.random() < 0.3:
            ocr = (w if rng.random() < 0.9 else rng.choice(words) for w in alt.split())
            texts["ocr"] = " ".join(ocr)
        b = make_block(raw, texts=texts)
        if rng.random() < 0.5:
            b = b.model_copy(update={"clean_text": raw})
        proms = tuple(
            CriticalPromotion(
                id=f"p{i}",
                signal=s,
                below=rng.choice([0.5, 0.8, 0.9]),
                support=50,
                rate_below=0.3,
                rate_above=0.01,
            )
            for i, s in enumerate(names)
            if rng.random() < 0.4
        )
        learned = LearnedScoring(snapshot="snapshot:001", sha="x", promotions=proms)
        c = ctx(
            displaced_in=["docling"] if rng.random() < 0.3 else [],
            in_overlap=rng.random() < 0.2,
            n_columns=rng.choice([1, 1, 2, 3]),
        )
        base = score_block(b, c, threshold=0.85)
        lrn = score_block(b, c, threshold=0.85, learned=learned)
        signal_sets.add(tuple(sorted(s.name.value for s in base.signals)))
        if base.confidence is None:
            continue
        scored += 1
        assert lrn.confidence is not None and lrn.confidence <= base.confidence, raw
        lowered += lrn.confidence < base.confidence
        if base.status == "queued":
            assert lrn.status == "queued", raw
    assert scored >= 900 and lowered > 0 and len(signal_sets) > 1
