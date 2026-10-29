"""Test 7: garbage_ratio."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockType, SignalName
from manuallabor.scoring.garbage import garbage_ratio, is_bad_token
from tests.scoring.conftest import Scored


def _v(text: str, table: bool = False) -> float:
    s = garbage_ratio(text, is_table=table)
    assert s is not None and not s.critical
    return s.value


def test_prose_and_spec_text() -> None:
    assert _v("Check the drive belt for wear before every use.") == 1.0
    assert _v("P/N 4471-A, 35 N·m, 0.25 mm ±0.05") == 1.0


def test_symbol_soup() -> None:
    assert _v("#$%@ ^&*(") <= 0.2


def test_g1_bad_chars() -> None:
    assert is_bad_token("(cid:12)")
    assert is_bad_token("ab�c")
    assert is_bad_token("a\x07b")
    assert not is_bad_token("soft­hyphen")


def test_fragmentation() -> None:
    assert _v("ovpmn o o s s e ln") <= 0.2
    assert _v("o o s s e ln", table=True) == 1.0  # fragmentation is not applied to tables


def test_mixed_script() -> None:
    assert is_bad_token("Тorque")  # Cyrillic Т + Latin
    assert not is_bad_token("5µm") and not is_bad_token("10kΩ")


def test_leaders_and_languages() -> None:
    assert _v("Introduction ........ 3") == 1.0
    assert _v("Überprüfen Sie das Drehmoment der Schrauben (35 N·m).") == 1.0
    assert _v("Vérifiez l'écrou « M8 » et la courroie d’entraînement.") == 1.0


def test_no_tokens_omitted() -> None:
    assert garbage_ratio("", is_table=False) is None
    assert garbage_ratio(" | | ", is_table=True) is None


@pytest.mark.parametrize("slug", ["clean", "twocol", "tables"])
def test_fixture_blocks_clean(scoredproj: Scored, slug: str) -> None:
    for b in scoredproj.blocks(slug):
        if b.type == BlockType.figure:
            continue
        s = garbage_ratio(b.raw_text, is_table=b.type == BlockType.table)
        assert s is None or s.value >= 0.9, (b.id, s)
        assert s is None or s.name == SignalName.garbage_ratio
