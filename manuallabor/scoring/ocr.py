"""ocr_mean / ocr_min from the OCR engine's per-word confidences (design 2.1)."""

from __future__ import annotations

import math

from manuallabor.contracts._base import round6
from manuallabor.contracts.block import Block, Signal
from manuallabor.contracts.enums import SignalName

OCR_SOURCES = frozenset({"ocr", "ocr_alt"})


def ocr_signals(block: Block, *, numeric: bool) -> list[Signal]:
    """Both signals, or none: only OCR-sourced blocks with countable words get them."""
    if block.raw_source not in OCR_SOURCES or not block.ocr_words:
        return []
    words = [
        w
        for w in block.ocr_words
        if w.text.strip() and not (len(w.text.strip()) == 1 and not w.text.strip().isalnum())
    ]
    if not words:
        return []
    confs = [w.confidence for w in words]
    mean = round6(math.fsum(confs) / len(confs))
    low = min(range(len(words)), key=lambda i: (confs[i], i))
    return [
        Signal(
            name=SignalName.ocr_mean,
            value=mean,
            critical=False,
            detail=f"mean over {len(words)} words",
        ),
        Signal(
            name=SignalName.ocr_min,
            value=round6(confs[low]),
            critical=numeric,
            detail=f"min {confs[low]:.3f} at {words[low].text.strip()[:40]!r}; {len(words)} words",
        ),
    ]
