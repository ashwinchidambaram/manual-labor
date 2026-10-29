"""Test 22: figure numbers and references."""

from __future__ import annotations

import pytest

from manuallabor.cleanup.refs import caption_number, find_refs, is_chaptered


@pytest.mark.parametrize(
    ("caption", "num"),
    [
        ("Figure 3.", "3"),
        ("Fig. 3", "3"),
        ("FIG 3", "3"),
        ("Figure 2-1", "2-1"),
        ("Figure 2.1", "2-1"),
        ("Fig. 2–01", "2-1"),
        ("Figure A-1", "A-1"),
        ("Figure 3a", "3a"),
        ("Figure 3A. Pump.", "3a"),
        ("Figure 03: Pump", "3"),
        ("Table 3. Torque", None),
        ("The figure 3 shows", None),
        ("", None),
        (None, None),
    ],
)
def test_22_caption_number(caption: str | None, num: str | None) -> None:
    assert caption_number(caption) == num


def _nums(text: str, chaptered: bool = False) -> list[str]:
    return [r.number for r in find_refs(text, chaptered)]


def test_22_find_refs() -> None:
    assert _nums("see Figure 3 for the layout") == ["3"]
    assert _nums("(see Fig. 3)") == ["3"]
    assert _nums("in the illustration (see\nFigure\n2).") == ["2"]
    assert _nums("Figures 3 and 4 show it") == ["3", "4"]
    assert _nums("Figs. 3–5") == ["3", "4", "5"]
    assert _nums("Figures 3 to 5") == ["3", "4", "5"]
    assert _nums("Figures 3, 4, and 6") == ["3", "4", "6"]
    assert _nums("Figure 2-1", chaptered=True) == ["2-1"]
    assert _nums("Figure 2–3", chaptered=True) == ["2-3"]
    assert _nums("Figure 2-1") == ["2-1"]  # non-chaptered, descending: kept as one number
    assert _nums("figure out the gap") == []
    assert _nums("Table 3 lists the torques") == []
    assert _nums("Fig 10mm") == []
    assert _nums("Figure 3a and Figure 3b") == ["3a", "3b"]
    assert _nums("See Figure 1. Then Figure 1 again.") == ["1", "1"]


def test_22_chaptered() -> None:
    assert is_chaptered(["2-1", None, "3"]) and not is_chaptered(["1", "2", None])
