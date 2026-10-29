"""Test 3: textlayer_vs_ocr."""

from __future__ import annotations

from manuallabor.scoring.agreement import textlayer_vs_ocr
from tests.scoring.conftest import make_block


def _sig(tl: str, ocr: str, numeric: bool = False):  # type: ignore[no-untyped-def]
    b = make_block(tl, texts={"pymupdf": tl, "docling": tl, "ocr": ocr})
    return textlayer_vs_ocr(b, numeric=numeric)


def test_identical() -> None:
    s = _sig("Check the drive belt.", "Check the drive belt.")
    assert s is not None and s.value == 1.0 and not s.critical


def test_measured_tesseract_degradations_are_free() -> None:
    tl = "• Tighten to 35 N·m ±0.05 mm with a 10 A fuse."
    ocr = "« Tighten to 35 N-m +0.05 mm witha 10A fuse."
    s = _sig(tl, ocr)
    assert s is not None and s.value == 1.0


def test_reverse_direction_is_a_mismatch() -> None:
    s = _sig("Gap +0.05 mm", "Gap ±0.05 mm")
    assert s is not None and s.value == 0.5 and s.critical


def test_confusable_digit() -> None:
    s = _sig("Tighten to 3S N·m", "Tighten to 35 N·m", numeric=True)
    assert s is not None and s.value == 0.5 and s.critical
    assert s.detail is not None and "confusable '3S' vs '35'" in s.detail


def test_ocr_empty() -> None:
    s = _sig("Tighten to 35 N·m", "")
    assert s is not None and s.value == 0.5 and s.critical
    assert s.detail == "OCR found no words in region"


def test_mojibake_text_layer() -> None:
    s = _sig("Wljkwhq wkh fryhu sodwh errowv wr 68 Q·p", "Tighten the cover plate bolts to 35 N·m")
    assert s is not None and s.value < 0.2 and s.critical


def test_criticality() -> None:
    s = _sig("Check the drive belt for wear", "Check the drive belt for wear", numeric=True)
    assert s is not None and s.critical  # numeric: always critical
    words = " ".join(f"word{chr(97 + i % 26)}" for i in range(4))
    s = _sig(words, "completely different text here")
    assert s is not None and s.value < 0.8 and s.critical


def test_omitted() -> None:
    assert (
        textlayer_vs_ocr(make_block("x", texts={"pymupdf": "x", "docling": "x"}), numeric=False)
        is None
    )
    b = make_block("x", source="ocr", texts={"ocr": "x", "ocr_alt": "x"})
    assert textlayer_vs_ocr(b, numeric=False) is None
    b = make_block("", texts={"pymupdf": "", "docling": "", "ocr": "x"})
    assert textlayer_vs_ocr(b, numeric=False) is None
