"""Test 1: comparison normalization N1-N6 and weighted_agreement steps 3-5."""

from __future__ import annotations

from manuallabor.scoring.text import (
    TOKW,
    cmp_tokens,
    normalize_cmp,
    numeric_context,
    weight,
    weighted_agreement,
)


def test_n1_nfkc_ligature_and_soft_hyphen() -> None:
    assert normalize_cmp("ﬁlter") == "filter"
    assert normalize_cmp("adjust­ment") == "adjustment"


def test_n2_dehyphenation() -> None:
    assert normalize_cmp("adjust-\nment") == "adjustment"
    assert normalize_cmp("adjust- \n  ment") == "adjustment"
    assert normalize_cmp("M8-\n10") == "M8-\n10"  # digits are not dehyphenated


def test_n3_bullets_stripped() -> None:
    for g in "•*¢«-+":
        assert normalize_cmp(f"{g} Check the belt") == "Check the belt"
    assert normalize_cmp("a\n  • b") == "a\nb"


def test_n4_tokens() -> None:
    assert TOKW.findall("0.25 mm ±0.05") == ["0.25", "mm", "±", "0.05"]
    assert TOKW.findall("M8") == ["M8"]
    assert TOKW.findall("N·m") == ["N", "·", "m"]
    assert TOKW.findall("a | b") == ["a", "b"]
    assert TOKW.findall("1,000.5 V") == ["1,000.5", "V"]


def test_n5_casefold_only_without_digits() -> None:
    assert cmp_tokens("Check M8 BOLT") == ["check", "M8", "bolt"]


def test_n6_weights_and_numeric_context() -> None:
    assert weight("35") == 3 and weight("M8") == 3 and weight("belt") == 1
    ctx = numeric_context(["a", "b", "c", "35", "d", "e", "f", "g"])
    assert ctx == [False, True, True, True, True, True, False, False]


def test_identical_and_empty() -> None:
    assert weighted_agreement([], [], directional=False).value == 1.0
    t = cmp_tokens("Tighten to 35 N·m")
    assert weighted_agreement(t, t, directional=False).value == 1.0


def test_step3_spacing_only_replace_matches() -> None:
    a, b = cmp_tokens("rated 10 A with a fuse"), cmp_tokens("rated 10A witha fuse")
    ag = weighted_agreement(a, b, directional=False)
    assert ag.value == 1.0 and ag.k_numeric == 0


def test_step4_directional_fold_one_way_only() -> None:
    tl, ocr = cmp_tokens("35 N·m ±0.05"), cmp_tokens("35 N-m +0.05")
    assert weighted_agreement(tl, ocr, directional=True).value == 1.0
    # reverse direction (OCR text in the text-layer slot) is a mismatch
    rev = weighted_agreement(ocr, tl, directional=True)
    assert rev.value <= 0.5 and rev.k_numeric >= 1
    # not directional: also a mismatch
    assert weighted_agreement(tl, ocr, directional=False).value <= 0.5


def test_step5_numeric_penalty_and_notes() -> None:
    ag = weighted_agreement(
        cmp_tokens("tighten 35 N·m"), cmp_tokens("tighten 36 N·m"), directional=False
    )
    assert ag.k_numeric == 1 and ag.value == 0.5
    assert ag.notes == ("'35' vs '36'",)


def test_step5_lookalike_note() -> None:
    ag = weighted_agreement(
        cmp_tokens("torque 3S N·m"), cmp_tokens("torque 35 N·m"), directional=True
    )
    assert ag.notes == ("confusable '3S' vs '35'",)
    ag = weighted_agreement(
        cmp_tokens("use M1O bolts"), cmp_tokens("use M10 bolts"), directional=False
    )
    assert ag.notes[0].startswith("confusable")


def test_notes_capped_at_three() -> None:
    a = cmp_tokens("a1 b c2 d e3 f g4 h i5")
    b = cmp_tokens("a9 b c8 d e7 f g6 h i0")
    assert len(weighted_agreement(a, b, directional=False).notes) == 3
