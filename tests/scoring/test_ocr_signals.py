"""Test 2: ocr_mean / ocr_min."""

from __future__ import annotations

from manuallabor.contracts.block import OcrWord
from manuallabor.contracts.enums import SignalName
from manuallabor.scoring.ocr import ocr_signals
from tests.scoring.conftest import make_block


def _b(confs: list[float], words: list[str] | None = None, source: str = "ocr"):  # type: ignore[no-untyped-def]
    words = words or [f"w{i}" for i in range(len(confs))]
    return make_block(
        " ".join(words),
        source=source,
        texts={source: " ".join(words)},
        ocr_words=[OcrWord(text=w, confidence=c) for w, c in zip(words, confs, strict=True)],
    )


def _vals(sigs):  # type: ignore[no-untyped-def]
    return {s.name: (s.value, s.critical) for s in sigs}


def test_uniform() -> None:
    v = _vals(ocr_signals(_b([0.97] * 5), numeric=False))
    assert v[SignalName.ocr_mean] == (0.97, False) and v[SignalName.ocr_min] == (0.97, False)


def test_one_low_word() -> None:
    v = _vals(ocr_signals(_b([0.97, 0.4, 0.97]), numeric=False))
    assert v[SignalName.ocr_min][0] == 0.4
    assert abs(v[SignalName.ocr_mean][0] - 0.78) < 1e-6


def test_all_zero() -> None:
    v = _vals(ocr_signals(_b([0.0, 0.0]), numeric=False))
    assert v[SignalName.ocr_min][0] == 0.0 and v[SignalName.ocr_mean][0] == 0.0


def test_bullet_word_excluded() -> None:
    sigs = ocr_signals(_b([0.045, 0.9, 0.9], ["¢", "Check", "belt"]), numeric=False)
    assert _vals(sigs)[SignalName.ocr_min][0] == 0.9
    assert ocr_signals(_b([0.1, 0.73], ["¢", "*"]), numeric=False) == []


def test_text_layer_block_omitted() -> None:
    b = _b([0.2, 0.3], source="pymupdf")
    assert ocr_signals(b, numeric=True) == []
    assert ocr_signals(make_block("x", source="ocr", texts={"ocr": "x"}), numeric=True) == []


def test_ocr_min_critical_iff_numeric() -> None:
    v = _vals(ocr_signals(_b([0.9, 0.8]), numeric=True))
    assert v[SignalName.ocr_min][1] is True and v[SignalName.ocr_mean][1] is False
    v = _vals(ocr_signals(_b([0.9, 0.8]), numeric=False))
    assert v[SignalName.ocr_min][1] is False


def test_detail_names_the_word() -> None:
    sigs = ocr_signals(_b([0.95, 0.787], ["Tighten", "M8"]), numeric=True)
    d = next(s for s in sigs if s.name == SignalName.ocr_min).detail
    assert d is not None and "'M8'" in d and "2 words" in d
