"""Test 13: numeric multiset and recorded text-layer/OCR variants."""

from __future__ import annotations

from manuallabor.contracts.block import NumericVariant
from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.scoring.faithfulness import check_faithfulness
from manuallabor.scoring.types import ReorderEvidence


def test_duplicated_number_fails() -> None:
    r = check_faithfulness("Use 2 bolts.", "Use 2 2 bolts.")
    assert not r.passed and K.numeric_mismatch in {v.kind for v in r.violations}


def test_reordered_numbers_under_accepted_reorder_pass() -> None:
    raw = "Tighten bolt A to 35 N·m\nTighten bolt B to 48 N·m"
    clean = "Tighten bolt B to 48 N·m Tighten bolt A to 35 N·m"
    r = check_faithfulness(raw, clean, evidence=ReorderEvidence(layout_risk=True))
    assert r.passed


VAR = NumericVariant(raw="3S", chosen="35", source="ocr", reason="text layer 3S, OCR reads 35")


def test_attested_variant_exempts() -> None:
    raw = "Tighten to 3S N·m."
    r = check_faithfulness(
        raw,
        "Tighten to 35 N·m.",
        variants=[VAR],
        variant_sources={"pymupdf": raw, "ocr": "Tighten to 35 N-m."},
        raw_source="pymupdf",
    )
    assert r.passed and r.numeric_variants == [VAR]


def test_textlayer_variant() -> None:
    v = NumericVariant(raw="36", chosen="35", source="textlayer", reason="OCR misread")
    raw = "Tighten to 36 N·m."
    r = check_faithfulness(
        raw,
        "Tighten to 35 N·m.",
        variants=[v],
        variant_sources={"ocr": raw, "ocr_alt": raw},
        raw_source="ocr",
    )
    assert not r.passed and r.numeric_variants == []  # 35 not attested in raw_source text
    r = check_faithfulness(
        raw,
        "Tighten to 35 N·m.",
        variants=[v],
        variant_sources={"ocr": "Tighten to 35 N·m."},
        raw_source="ocr",
    )
    assert r.passed


def test_unattested_variant_ignored() -> None:
    raw = "Tighten to 3S N·m."
    r = check_faithfulness(
        raw,
        "Tighten to 35 N·m.",
        variants=[VAR],
        variant_sources={"pymupdf": raw, "ocr": "Tighten to 3S N-m."},
        raw_source="pymupdf",
    )
    assert not r.passed and r.numeric_variants == []
    r = check_faithfulness(
        "Tighten to 36 N·m.",
        "Tighten to 35 N·m.",
        variants=[VAR],
        variant_sources={"ocr": "35"},
        raw_source="pymupdf",
    )
    assert not r.passed and r.numeric_variants == []  # raw does not contain the variant


def test_multiple_variants() -> None:
    v2 = NumericVariant(raw="4B", chosen="48", source="ocr", reason="ocr")
    raw = "A 3S N·m, B 4B N·m."
    r = check_faithfulness(
        raw,
        "A 35 N·m, B 48 N·m.",
        variants=[VAR, v2],
        variant_sources={"pymupdf": raw, "ocr": "A 35 N-m, B 48 N-m."},
        raw_source="pymupdf",
    )
    assert r.passed and r.numeric_variants == [VAR, v2]
