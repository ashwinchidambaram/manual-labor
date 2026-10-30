"""Module 12 review: level (a)'s early exits (rewrite guard, size guard) must still compare
numbers, so a changed, dropped or added number is always reported as ``numeric_mismatch``."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.scoring.faithfulness import canonicalize, check_faithfulness
from manuallabor.scoring.types import FAITH_MAX_CHARS, FAITH_REWRITE_QUICK_RATIO


def _numeric(r_violations: list) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    return sorted((v.raw, v.clean) for v in r_violations if v.kind == K.numeric_mismatch)


def test_rewrite_below_quick_ratio_reports_changed_number() -> None:
    raw = "Tighten the cover bolts to 25 Nm."
    clean = "XYZ QJK 52 Nm !!"
    rc, cc = canonicalize(raw).mt.text, canonicalize(clean).mt.text
    sm = SequenceMatcher(None, rc, cc, autojunk=False)
    assert sm.quick_ratio() < FAITH_REWRITE_QUICK_RATIO  # precondition: the rewrite guard fires
    r = check_faithfulness(raw, clean)
    assert not r.passed
    whole = [v for v in r.violations if v.kind == K.deletion]
    assert len(whole) == 1 and (whole[0].raw_start, whole[0].raw_end) == (0, len(raw))
    assert (whole[0].clean_start, whole[0].clean_end) == (0, len(clean))
    # 25 dropped from raw, 52 added in clean: both reported, with exact spans
    assert _numeric(r.violations) == [("", "52"), ("25", "")]
    for v in r.violations:
        if v.kind == K.numeric_mismatch and v.raw_start is not None:
            assert raw[v.raw_start : v.raw_end] == v.raw == "25"
        if v.kind == K.numeric_mismatch and v.clean_start is not None:
            assert clean[v.clean_start : v.clean_end] == v.clean == "52"


def test_oversize_pair_reports_dropped_number() -> None:
    filler = "Check the drive belt for wear.\n" * (FAITH_MAX_CHARS // 50)
    raw = filler + "Torque the pulley nut to 25 Nm."
    clean = filler + "Torque the pulley nut."
    assert len(raw) + len(clean) > FAITH_MAX_CHARS  # precondition: the size guard fires
    r = check_faithfulness(raw, clean)
    assert not r.passed
    kinds = Counter(v.kind for v in r.violations)
    assert kinds[K.deletion] == 1
    assert _numeric(r.violations) == [("25", "")]
    v = next(v for v in r.violations if v.kind == K.numeric_mismatch)
    assert v.raw_start is not None and raw[v.raw_start : v.raw_end] == "25"
    assert v.clean_start is None


def test_oversize_pair_reports_changed_and_added_numbers() -> None:
    filler = "Check the drive belt for wear.\n" * (FAITH_MAX_CHARS // 50)
    raw = filler + "Torque to 25 Nm."
    clean = filler + "Torque to 52 Nm, then 3 more turns."
    assert len(raw) + len(clean) > FAITH_MAX_CHARS
    r = check_faithfulness(raw, clean)
    assert not r.passed
    assert _numeric(r.violations) == [("", "3"), ("", "52"), ("25", "")]


def test_early_exits_do_not_double_report_numbers() -> None:
    """One numeric_mismatch per unmatched number occurrence, never two."""
    r = check_faithfulness("Tighten the cover bolts to 25 Nm.", "XYZ QJK 52 Nm !!")
    assert Counter(v.kind for v in r.violations)[K.numeric_mismatch] == 2


def test_early_exits_without_number_changes_stay_one_deletion() -> None:
    # same numbers on both sides: only the whole-text deletion, as before
    r = check_faithfulness("Tighten the cover bolts to 25 Nm.", "XYZ QJK 25 Nm !!")
    assert not r.passed and [v.kind for v in r.violations] == [K.deletion]
