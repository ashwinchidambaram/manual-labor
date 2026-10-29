"""parser_agreement and textlayer_vs_ocr (design 2.2, 2.3)."""

from __future__ import annotations

from typing import Final

from manuallabor.contracts.block import Block, Signal
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.text import cmp_tokens, weighted_agreement
from manuallabor.scoring.types import (
    AGREEMENT_CRITICAL_BELOW,
    OCR_EMPTY_VALUE,
    SINGLE_SOURCE_VALUE,
    truncate,
)

PAIRS: Final = (("pymupdf", "docling"), ("ocr", "ocr_alt"), ("docx", "docling"))
TEXT_LAYER_SOURCES: Final = frozenset({"pymupdf", "docling"})
_PAIR_FOR_SOURCE: Final = {
    "pymupdf": ("pymupdf", "docling"),
    "docling": ("pymupdf", "docling"),
    "ocr": ("ocr", "ocr_alt"),
    "ocr_alt": ("ocr", "ocr_alt"),
    "docx": ("docx", "docling"),
}


def _critical(value: float, numeric: bool) -> bool:
    return numeric or value < AGREEMENT_CRITICAL_BELOW


def _detail(head: str, value: float, notes: tuple[str, ...], numeric_kind: bool) -> str:
    s = f"{head} {value:g}"
    if notes:
        s += ("; numeric: " if numeric_kind else "; ") + "; ".join(notes)
    return truncate(s)


def parser_agreement(
    block: Block, parser_versions: dict[str, str], *, numeric: bool
) -> tuple[Signal | None, str | None]:
    """(signal or None, unavailable-reader note or None)."""
    texts = block.raw_text_by_parser
    for a, b in PAIRS:
        if a in texts and b in texts:
            ta, tb = texts[a], texts[b]
            if not ta.strip() and not tb.strip():
                return None, None
            ag = weighted_agreement(cmp_tokens(ta), cmp_tokens(tb), directional=False)
            return (
                Signal(
                    name=SignalName.parser_agreement,
                    value=ag.value,
                    critical=_critical(ag.value, numeric),
                    detail=_detail(f"{a} vs {b}", ag.value, ag.notes, ag.k_numeric > 0),
                ),
                None,
            )
    pair = _PAIR_FOR_SOURCE.get(block.raw_source)
    if pair is None or not block.raw_text.strip():
        return None, None
    present = block.raw_source if block.raw_source in texts else None
    missing = pair[1] if block.raw_source == pair[0] else pair[0]
    if present is None and pair[0] in texts:
        present, missing = pair[0], pair[1]
    elif present is None and pair[1] in texts:
        present, missing = pair[1], pair[0]
    version = parser_versions.get(missing)
    if version is None or version == "unavailable":
        return None, f"parser_agreement unavailable: {missing}"
    reader = present or block.raw_source
    return (
        Signal(
            name=SignalName.parser_agreement,
            value=SINGLE_SOURCE_VALUE,
            critical=_critical(SINGLE_SOURCE_VALUE, numeric),
            detail=f"only {reader} read this region",
        ),
        None,
    )


def textlayer_vs_ocr(block: Block, *, numeric: bool) -> Signal | None:
    texts = block.raw_text_by_parser
    if block.raw_source not in TEXT_LAYER_SOURCES or "ocr" not in texts:
        return None
    a = texts.get(block.raw_source, block.raw_text)
    if not a.strip():
        return None
    b = texts["ocr"]
    if not b.strip():
        return Signal(
            name=SignalName.textlayer_vs_ocr,
            value=OCR_EMPTY_VALUE,
            critical=_critical(OCR_EMPTY_VALUE, numeric),
            detail="OCR found no words in region",
        )
    ag = weighted_agreement(cmp_tokens(a), cmp_tokens(b), directional=True)
    return Signal(
        name=SignalName.textlayer_vs_ocr,
        value=ag.value,
        critical=_critical(ag.value, numeric),
        detail=_detail("text layer vs OCR", ag.value, ag.notes, False),
    )
