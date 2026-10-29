"""Test 14: the reorder allowance (design 4.5)."""

from __future__ import annotations

from manuallabor.contracts.enums import DiffOpKind, SignalName
from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.scoring.faithfulness import check_faithfulness, check_faithfulness_ex, cover
from manuallabor.scoring.pipeline import score_block
from manuallabor.scoring.types import ReorderEvidence
from tests.scoring.conftest import ctx, make_block

A = ["Keep the area around the", "cover plate free of oil", "before you start work."]
B = ["Record any damage to the", "gearbox housing in the", "service log every day."]
INTERLEAVED = "\n".join(x for pair in zip(A, B, strict=True) for x in pair)
FIXED = " ".join(A + B)


def test_deinterleaved_lines_layout_risk_alone_fails() -> None:
    """Layout risk (multi-column page, displaced block) is never sufficient on its own."""
    r = check_faithfulness(INTERLEAVED, FIXED, evidence=ReorderEvidence(layout_risk=True))
    assert not r.passed and {v.kind for v in r.violations} == {K.reorder}


def test_deinterleaved_lines_attested_by_other_parser_pass() -> None:
    other = "\n".join(A + B)  # the other parser read the columns in the clean order
    out = check_faithfulness_ex(
        INTERLEAVED, FIXED, evidence=ReorderEvidence(layout_risk=True, alt_texts=(other,))
    )
    assert out.result.passed and out.reordered
    ops = [op for op in out.result.diff if op.op == DiffOpKind.reorder]
    assert ops and all(op.allowed for op in ops)


STEPS = "1. Remove the cover plate.\n2. Lift out the rotor.\n3. Refit the cover plate."
STEPS_MOVED = "3. Refit the cover plate.\n1. Remove the cover plate.\n2. Lift out the rotor."


def test_step_moved_on_two_column_page_without_reader_fails() -> None:
    """Reviewer's blocker: step 3 moved first on an n_columns=2 page passed at 0.9 and was
    auto-approved. No other reader saw that order, so it is a reorder violation."""
    b = make_block(STEPS, clean_text=STEPS_MOVED)  # pymupdf and docling both read STEPS
    s = score_block(b, ctx(n_columns=2), threshold=0.85)
    f = next(x for x in s.signals if x.name == SignalName.faithfulness)
    assert f.value == 0.0
    assert s.faithfulness is not None and K.reorder in {v.kind for v in s.faithfulness.violations}
    assert s.confidence == 0.0 and s.status == "queued"


def test_step_moved_attested_by_other_parser_passes_at_09() -> None:
    texts = {"pymupdf": STEPS, "docling": STEPS_MOVED}
    b = make_block(STEPS, clean_text=STEPS_MOVED, texts=texts)
    s = score_block(b, ctx(n_columns=2), threshold=0.85)
    f = next(x for x in s.signals if x.name == SignalName.faithfulness)
    assert f.value == 0.9 and s.faithfulness is not None and s.faithfulness.passed
    # the same reader evidence is honoured on a single-column page too (evidence, not layout)
    s1 = score_block(b, ctx(n_columns=1), threshold=0.85)
    assert next(x for x in s1.signals if x.name == SignalName.faithfulness).value == 0.9


def test_ocr_reader_attests_too() -> None:
    texts = {"pymupdf": STEPS, "docling": STEPS, "ocr": STEPS_MOVED.replace("\n", " ")}
    b = make_block(STEPS, clean_text=STEPS_MOVED, texts=texts)
    s = score_block(b, ctx(n_columns=2), threshold=0.85)
    assert next(x for x in s.signals if x.name == SignalName.faithfulness).value == 0.9


def test_same_without_evidence_is_reorder_violation() -> None:
    r = check_faithfulness(INTERLEAVED, FIXED)
    assert not r.passed and {v.kind for v in r.violations} == {K.reorder}
    for v in r.violations:
        assert v.raw_start is not None and v.raw_end is not None
        assert INTERLEAVED[v.raw_start : v.raw_end] == v.raw
        assert v.clean_start is not None and v.clean_end is not None
        assert FIXED[v.clean_start : v.clean_end] == v.clean
        assert v.raw == v.clean  # a moved unit is the same text


S1, S2 = "Loosen the four cover bolts.", "Lift the cover off the housing."


def test_attested_sentence_swap_passes() -> None:
    raw = f"{S1} {S2}"
    out = check_faithfulness_ex(
        raw, f"{S2} {S1}", evidence=ReorderEvidence(alt_texts=(f"{S2}\n{S1}",))
    )
    assert out.result.passed and out.reordered


def test_unattested_sentence_swap_fails_even_with_layout_risk() -> None:
    r = check_faithfulness(f"{S1} {S2}", f"{S2} {S1}", evidence=ReorderEvidence(layout_risk=True))
    assert not r.passed and K.reorder in {v.kind for v in r.violations}


def test_reorder_plus_inserted_word_fails() -> None:
    r = check_faithfulness(
        INTERLEAVED,
        FIXED.replace("service log", "service log not"),
        evidence=ReorderEvidence(layout_risk=True, alt_texts=(FIXED,)),
    )
    assert not r.passed and K.insertion in {v.kind for v in r.violations}


def test_step_cap_fails_closed() -> None:
    units = ["a", "a a", "a a a", "a a a a", "b"]
    target = " ".join(["a"] * 30) + " c"
    assert cover(units * 3, target, max_steps=50) is None
    assert cover(["x", "y"], "y x") == [(1, 0), (0, 2)]


def test_too_many_units_fail_closed() -> None:
    lines = [
        f"line number {chr(97 + i % 26)}{chr(97 + i // 26 % 26)}{i // 676}" for i in range(201)
    ]
    raw = "\n".join(lines)
    clean = " ".join(lines[1:] + lines[:1])
    r = check_faithfulness(raw, clean, evidence=ReorderEvidence(layout_risk=True))
    assert not r.passed
    assert K.reorder not in {v.kind for v in r.violations}  # never even attempted
