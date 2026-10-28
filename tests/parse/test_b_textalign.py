"""Test 22: split_text_by_alignment."""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from manuallabor.parse.textalign import split_text_by_alignment


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_exact_on_clean_input() -> None:
    parts = ["Tighten the bolts to 35 N·m.", "Allow the unit to cool.", "Refit the cover plate."]
    whole = " ".join(parts)
    assert split_text_by_alignment(whole, parts) == parts
    assert split_text_by_alignment("\n".join(parts), parts) == parts


def test_robust_to_two_char_typo() -> None:
    parts = ["Tighten the bolts to 35 N·m.", "Allow the unit to cool.", "Refit the cover plate."]
    whole = "Tighten the bolts to 35 N-m. Allow the unlt to cool. Refit the cover plate."
    out = split_text_by_alignment(whole, parts)
    assert out == [
        "Tighten the bolts to 35 N-m.",
        "Allow the unlt to cool.",
        "Refit the cover plate.",
    ]
    typo_at_boundary = "Tighten the bolts to 35 N·m. Allow the unit to cooI. Refit the cover plate."
    assert split_text_by_alignment(typo_at_boundary, parts)[2] == "Refit the cover plate."


def test_degenerate_inputs() -> None:
    assert split_text_by_alignment("abc", []) == []
    assert split_text_by_alignment("  abc  ", ["abc"]) == ["abc"]
    out = split_text_by_alignment("alpha beta", ["alpha", "", "beta"])
    assert len(out) == 3
    assert _squash("".join(out)) == "alphabeta"


def test_deterministic() -> None:
    parts = ["one two three", "four five six", "seven eight"]
    whole = "one two thre four fiv six seven eight"
    first = split_text_by_alignment(whole, parts)
    assert all(split_text_by_alignment(whole, parts) == first for _ in range(5))


_word = st.text(alphabet="abcdefghij0123456789.-", min_size=1, max_size=8)
_part = st.lists(_word, min_size=1, max_size=6).map(" ".join)


@settings(max_examples=150, deadline=None)
@given(st.lists(_part, min_size=1, max_size=6), st.text(alphabet="abcdefg hij\n", max_size=60))
def test_concatenation_invariant(parts: list[str], whole: str) -> None:
    out = split_text_by_alignment(whole, parts)
    assert len(out) == len(parts)
    assert _squash("".join(out)) == _squash(whole)


@settings(max_examples=100, deadline=None)
@given(st.lists(_part, min_size=2, max_size=6))
def test_exact_roundtrip_property(parts: list[str]) -> None:
    assert split_text_by_alignment(" ".join(parts), parts) == parts
