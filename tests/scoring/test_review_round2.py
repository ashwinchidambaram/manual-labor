"""Module 3 second review: numeric-variant position, page-number slot, whole-unit reorder
evidence, short numeric verifier spans, unit-lexicon gaps."""

from __future__ import annotations

import pytest

from manuallabor.contracts.block import FaithfulnessResult, NumericVariant
from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.faithfulness import check_faithfulness, ocr_confusable
from manuallabor.scoring.numeric import find_numeric_specs
from manuallabor.scoring.pipeline import score_block
from manuallabor.scoring.verifier import validate_answer
from tests.scoring.conftest import ctx, make_block

# -- 1. numeric variant: same numeric-token index and an OCR-confusable pair -----------------


def _var(raw: str, clean: str, v: NumericVariant, ocr: str) -> FaithfulnessResult:
    return check_faithfulness(
        raw,
        clean,
        variants=[v],
        variant_sources={"pymupdf": raw, "ocr": ocr},
        raw_source="pymupdf",
    )


V35_40 = NumericVariant(raw="35", chosen="40", source="ocr", reason="t")
V3S_35 = NumericVariant(raw="3S", chosen="35", source="ocr", reason="t")


def test_variant_adjacent_token_laundering_fails() -> None:
    """The reviewer's case: OCR read 85 where raw has 35; 40 is the NEXT number."""
    r = _var("Sizes 30 35 40 mm", "Sizes 30 40 40 mm", V35_40, "Sizes 30 85 40 mm")
    assert not r.passed and r.numeric_variants == []
    assert K.numeric_mismatch in {v.kind for v in r.violations}


def test_variant_confusable_at_same_numeric_index_passes() -> None:
    r = _var("Sizes 30 3S 40 mm", "Sizes 30 35 40 mm", V3S_35, "Sizes 30 35 40 mm")
    assert r.passed and r.numeric_variants == [V3S_35]
    # word tokens in between do not shift the numeric index (merged words are fine)
    r = _var("Sizes 30 and 3S or 40 mm", "Sizes 30 and 35 or 40 mm", V3S_35, "Sizes30 and 35 40")
    assert r.passed


def test_variant_not_confusable_fails_even_at_the_right_index() -> None:
    r = _var("Set 35 Nm then check 40 rpm.", "Set 40 Nm then check 40 rpm.", V35_40,
             "Set 40 Nm then check 40 rpm.")  # fmt: skip
    assert not r.passed and r.numeric_variants == []


def test_variant_right_digits_wrong_numeric_index_fails() -> None:
    # OCR has 35 only as the next number (index 2), not at raw's numeric index 1
    r = _var("Sizes 30 3S 40 mm", "Sizes 30 35 40 mm", V3S_35, "Sizes 30 3S 35 mm")
    assert not r.passed and r.numeric_variants == []
    r = _var("Sizes 30 3S 40 mm", "Sizes 30 35 40 mm", V3S_35, "Sizes 35 3S 40 mm")
    assert not r.passed and r.numeric_variants == []


@pytest.mark.parametrize(
    ("raw", "chosen", "ok"),
    [
        ("3S", "35", True),
        ("4B", "48", True),
        ("l0", "10", True),
        ("I2", "12", True),
        ("1O", "10", True),
        ("Z5", "25", True),
        ("G0", "60", True),
        ("9g", "99", True),
        ("3,5", "3.5", True),
        # adding or dropping a digit is never a look-alike (module 10 fix: it needs two
        # attesters under the design rule, not one reader plus a "confusable" pass)
        ("35", "355", False),
        ("355", "35", False),
        ("35", "350", False),
        ("35", "3", False),
        ("1", "11", False),
        ("3S", "350", False),
        ("1O", "10", True),
        ("B8", "88", True),
        ("35", "3S", True),
        ("0.5", "O,5", True),
        ("35", "45", False),  # 3/4 is not a confusable pair
        ("35", "40", False),
        ("36", "35", False),
        ("35", "35", False),
        ("3.5", "35", False),  # a dropped decimal point is not a dropped digit
        ("35", "3500", False),
        ("1/2", "12", False),
    ],
)
def test_ocr_confusable(raw: str, chosen: str, ok: bool) -> None:
    assert ocr_confusable(raw, chosen) is ok


# -- 2. page number only in the {n} slot; exact removal only for this page ------------------

BODY = "Remove the cover plate."
H12 = "Acme X200 Service Manual · 12 V"


def _hf(raw: str, clean: str, page: int, **kw) -> FaithfulnessResult:  # type: ignore[no-untyped-def]
    return check_faithfulness(raw, clean, page=page, **kw)


def test_hf_constant_digit_run_never_takes_the_page_number() -> None:
    r = _hf(H12.replace("12", "13") + "\n" + BODY, BODY, 13, hf_strings=[H12])
    assert not r.passed
    pages = {H12: [1, 2, 3, 4]}
    r = _hf(H12.replace("12", "13") + "\n" + BODY, BODY, 13, hf_pages=pages)
    assert not r.passed
    # the constant itself is removable on any page
    assert _hf(H12 + "\n" + BODY, BODY, 13, hf_strings=[H12]).passed
    assert _hf(H12 + "\n" + BODY, BODY, 13, hf_pages=pages).passed


def test_hf_page_of_total_other_run_must_match() -> None:
    hf = ["Page 33 of 60", "Page 34 of 60"]
    assert not _hf(BODY + "\nPage 35 of 35", BODY, 35, hf_strings=hf).passed
    assert _hf(BODY + "\nPage 35 of 60", BODY, 35, hf_strings=hf).passed
    pages = {"Page 34 of 60": [34]}
    assert not _hf(BODY + "\nPage 35 of 35", BODY, 35, hf_pages=pages).passed
    assert _hf(BODY + "\nPage 35 of 60", BODY, 35, hf_pages=pages).passed


def test_hf_other_pages_footer_is_not_removable() -> None:
    hf = ["Page 33", "Page 34"]
    r = _hf(BODY + "\nPage 34", BODY, 35, hf_strings=hf)
    assert not r.passed and any("34" in v.raw for v in r.violations)
    r = _hf(BODY + "\nPage 34", BODY, 35, hf_pages={"Page 34": [34]})
    assert not r.passed
    # a string recorded on a single page is not a doc-wide constant
    r = _hf(BODY + "\nService Bulletin", BODY, 35, hf_pages={"Service Bulletin": [34]})
    assert not r.passed


def test_hf_this_pages_footer_passes() -> None:
    assert _hf(BODY + "\nPage 35", BODY, 35, hf_strings=["Page 33", "Page 34"]).passed
    assert _hf(BODY + "\nPage 35", BODY, 35, hf_pages={"Page 34": [34]}).passed
    assert _hf(BODY + "\nPage 35", BODY, 35, hf_pages={"Page 35": [35]}).passed
    # an exactly recorded string of this page, whatever its template
    assert _hf(BODY + "\n2-35", BODY, 35, hf_pages={"TM 2-35": [35]}).passed is False
    assert _hf(BODY + "\nTM 2-35", BODY, 35, hf_pages={"TM 2-35": [35], "TM 3-1": [40]}).passed


def test_hf_pages_reach_the_pipeline() -> None:
    raw = "Set the gap.\nPage 34"
    b = make_block(raw, page=35, clean_text="Set the gap.")
    s = score_block(b, ctx(hf_strings=["Page 34"], hf_pages={"Page 34": [34]}), threshold=0.85)
    assert s.faithfulness is not None and not s.faithfulness.passed
    b = make_block(raw, page=34, clean_text="Set the gap.")
    s = score_block(b, ctx(hf_strings=["Page 34"], hf_pages={"Page 34": [34]}), threshold=0.85)
    assert s.faithfulness is not None and s.faithfulness.passed


# -- 3. reorder evidence matches whole units -----------------------------------------------


def test_reorder_evidence_is_not_a_substring_of_a_longer_number() -> None:
    raw = "5 Nm is the limit.\nTighten the nut."
    clean = "Tighten the nut.\n5 Nm is the limit."
    b = make_block(
        raw,
        clean_text=clean,
        texts={"pymupdf": raw, "docling": "Tighten the nut. 15 Nm is the limit."},
    )
    s = score_block(b, ctx(n_columns=2), threshold=0.85)
    f = next(x for x in s.signals if x.name == SignalName.faithfulness)
    assert f.value == 0.0 and s.faithfulness is not None
    assert {v.kind for v in s.faithfulness.violations} == {K.reorder}
    # the same with a whole-unit reading in the clean order is accepted
    b = make_block(
        raw,
        clean_text=clean,
        texts={"pymupdf": raw, "docling": "Tighten the nut. 5 Nm is the limit."},
    )
    s = score_block(b, ctx(n_columns=2), threshold=0.85)
    f = next(x for x in s.signals if x.name == SignalName.faithfulness)
    assert f.value == 0.9


def test_reorder_evidence_unit_must_end_on_a_boundary() -> None:
    from manuallabor.scoring.types import ReorderEvidence

    raw = "4 drops of oil\nCheck it"
    clean = "Check it 4 drops of oil"
    r = check_faithfulness(
        raw, clean, evidence=ReorderEvidence(alt_texts=("Check items 4 drops of oil",))
    )
    assert not r.passed and {v.kind for v in r.violations} == {K.reorder}
    r = check_faithfulness(
        raw, clean, evidence=ReorderEvidence(alt_texts=("Check it 4 drops of oil",))
    )
    assert r.passed


# -- 4. verifier: short numeric spans count ------------------------------------------------

VRAW = "Torque the 35 Nm bolts on the cover. Set gap to 5 mm. Do not reuse gaskets."


@pytest.mark.parametrize("reply", ["35", "35 ", "5", "'5'"])
def test_verifier_short_numeric_span_flags(reply: str) -> None:
    outcome, s = validate_answer(reply, VRAW, VRAW)
    assert outcome == "flag" and s is not None and s.value == 0.2


@pytest.mark.parametrize("reply", ["no", "the", "Do", ".", "--", "3", "53", "e"])
def test_verifier_short_non_numeric_or_absent_ignored(reply: str) -> None:
    outcome, s = validate_answer(reply, VRAW, VRAW)
    assert outcome == "verifier_invalid" and s is None


# -- 5. unit lexicon gaps --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("Set the supply to 5V.", "5V"),
        ("Fit a 3W lamp.", "3W"),
        ("Use 1/4-20 UNC screws.", "1/4-20 UNC"),
        ("Use #10-32 screws.", "#10-32"),
        ("Use 3/8-16 bolts.", "3/8-16"),
        ("Use 0.250-28 UNF studs.", "0.250-28 UNF"),
        ("Drill 2 in. from the edge.", "2 in."),
        ("Torque to 100 ft.lb.", "Torque to 100 ft.lb."),
        ("Capacity 10,000 pounds", "Capacity 10,000 pounds"),
    ],
)
def test_lexicon_gap_fires_with_full_span(text: str, spec: str) -> None:
    assert spec in find_numeric_specs(text, None), find_numeric_specs(text, None)


def test_spec_word_detail_is_never_a_truncated_number() -> None:
    specs = find_numeric_specs("Torque to 100 ft.lb.", None)
    assert "Torque to 1" not in specs and all(not s.endswith(" 1") for s in specs)


@pytest.mark.parametrize(
    "text",
    ["ME -3895-332-12/2-4", "TM -5-3895", "Section 1V. TROUBLESHOOTING", "See paragraph 2-4."],
)
def test_lexicon_gap_does_not_fire(text: str) -> None:
    assert find_numeric_specs(text, None) == [], find_numeric_specs(text, None)


def test_numeric_detail_shows_full_spec() -> None:
    b = make_block("Torque to 100 ft.lb.")
    s = score_block(b, ctx(), threshold=0.85)
    sig = next(x for x in s.signals if x.name == SignalName.has_numeric_spec)
    assert sig.detail is not None and "Torque to 100 ft.lb." in sig.detail
    assert "Torque to 1;" not in sig.detail
