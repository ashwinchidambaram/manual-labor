"""Test 4: parser_agreement."""

from __future__ import annotations

from manuallabor.scoring.agreement import parser_agreement
from tests.scoring.conftest import make_block

PV = {"pymupdf": "1", "docling": "2", "ocr": "t", "ocr_alt": "r"}


def _pa(a: str, b: str, numeric: bool = False):  # type: ignore[no-untyped-def]
    return parser_agreement(make_block(a, texts={"pymupdf": a, "docling": b}), PV, numeric=numeric)


def test_identical() -> None:
    s, note = _pa("Check the belt.", "Check the belt.")
    assert s is not None and s.value == 1.0 and not s.critical and note is None


def test_docling_drops_bullets_and_joins_lines() -> None:
    s, _ = _pa(
        "• Check the belt\nfor wear.\n• Replace it.", "Check the belt for wear.\nReplace it."
    )
    assert s is not None and s.value == 1.0


def test_numeric_differences() -> None:
    s, _ = _pa("Tighten to 35 N·m then wait.", "Tighten to 36 N·m then wait.")
    assert s is not None and s.value == 0.5 and s.critical
    assert s.detail is not None and "numeric: '35' vs '36'" in s.detail
    s, _ = _pa(
        "Tighten to 35 N·m. Check every bolt carefully afterwards. Then torque 48 N·m.",
        "Tighten to 36 N·m. Check every bolt carefully afterwards. Then torque 49 N·m.",
    )
    assert s is not None and s.value == 0.25


def test_one_word_in_thirty_is_soft() -> None:
    words = [f"word{chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(30)]
    other = list(words)
    other[15] = "changed"
    s, _ = _pa(" ".join(words), " ".join(other))
    assert s is not None and abs(s.value - 29 / 30) < 1e-6 and not s.critical


def test_interleaved_columns_critical() -> None:
    a = "Keep the area clean\nand dry at all times\nbefore any work starts"
    b = "Record any damage\nin the service log\nand report it"
    mixed = "\n".join(x for pair in zip(a.split("\n"), b.split("\n"), strict=True) for x in pair)
    s, _ = _pa(mixed, a)
    assert s is not None and s.value < 0.8 and s.critical


def test_single_source() -> None:
    b = make_block("Only one reader.", texts={"pymupdf": "Only one reader.", "ocr": "x"})
    s, note = parser_agreement(b, PV, numeric=False)
    assert s is not None and s.value == 0.6 and s.detail == "only pymupdf read this region"
    assert s.critical  # 0.6 < 0.8


def test_other_reader_unavailable() -> None:
    b = make_block("Scanned text.", source="ocr", texts={"ocr": "Scanned text."})
    s, note = parser_agreement(b, {**PV, "ocr_alt": "unavailable"}, numeric=False)
    assert s is None and note == "parser_agreement unavailable: ocr_alt"
    s, note = parser_agreement(b, {"ocr": "t"}, numeric=False)
    assert s is None and note == "parser_agreement unavailable: ocr_alt"


def test_both_empty_omitted() -> None:
    s, note = parser_agreement(
        make_block("", texts={"pymupdf": "", "docling": " "}), PV, numeric=False
    )
    assert s is None and note is None


def test_pair_order() -> None:
    b = make_block("a b", source="ocr", texts={"ocr": "a b", "ocr_alt": "a c"})
    s, _ = parser_agreement(b, PV, numeric=False)
    assert s is not None and s.detail is not None and s.detail.startswith("ocr vs ocr_alt")
    b = make_block("a b", source="docx", texts={"docx": "a b", "docling": "a b"})
    s, _ = parser_agreement(b, PV, numeric=False)
    assert s is not None and s.detail is not None and s.detail.startswith("docx vs docling")
