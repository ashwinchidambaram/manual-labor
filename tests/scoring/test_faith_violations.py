"""Test 12: everything outside the allowed edits is a violation, with exact spans."""

from __future__ import annotations

from manuallabor.contracts.block import FaithfulnessResult, TableCell, TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.scoring.faithfulness import check_faithfulness

HF = ["Acme X200 Service Manual", "Page 3"]


def bad(raw: str, clean: str, **kw) -> FaithfulnessResult:  # type: ignore[no-untyped-def]
    r = check_faithfulness(raw, clean, hf_strings=kw.pop("hf_strings", HF), **kw)
    assert not r.passed and r.violations
    for v in r.violations:
        if v.raw_start is not None:
            assert v.raw_end is not None and 0 <= v.raw_start <= v.raw_end <= len(raw)
            assert raw[v.raw_start : v.raw_end] == v.raw
        if v.clean_start is not None:
            assert v.clean_end is not None and 0 <= v.clean_start <= v.clean_end <= len(clean)
            assert clean[v.clean_start : v.clean_end] == v.clean
    # every diff op that overlaps a violation is not allowed
    for op in r.diff:
        for v in r.violations:
            hits_raw = (
                v.raw_start is not None
                and op.raw_start < op.raw_end
                and op.raw_start < (v.raw_end or 0)
                and v.raw_start < op.raw_end
            )
            hits_clean = (
                v.clean_start is not None
                and op.clean_start < op.clean_end
                and op.clean_start < (v.clean_end or 0)
                and v.clean_start < op.clean_end
            )
            if op.op.value != "equal" and (hits_raw or hits_clean):
                assert not op.allowed
    assert any(not op.allowed for op in r.diff)
    return r


def kinds(r: FaithfulnessResult) -> set[K]:
    return {v.kind for v in r.violations}


def test_inserted_word() -> None:
    r = bad("Check the drive belt.", "Check not the drive belt.")
    v = next(v for v in r.violations if v.kind == K.insertion)
    assert "not" in v.clean and v.raw == ""


def test_deleted_word() -> None:
    r = bad("Do not remove the cover.", "Do remove the cover.")
    assert K.deletion in kinds(r)
    assert any("not" in v.raw for v in r.violations)


def test_digit_swap() -> None:
    r = bad("Tighten to 35 N·m.", "Tighten to 36 N·m.")
    assert kinds(r) == {K.deletion, K.numeric_mismatch}
    nm = [v for v in r.violations if v.kind == K.numeric_mismatch]
    assert {v.raw for v in nm} == {"35", ""} and {v.clean for v in nm} == {"", "36"}


def test_token_merge_and_split() -> None:
    assert K.deletion in kinds(bad("walk a cross the yard", "walk across the yard"))
    assert K.insertion in kinds(bad("a notable change", "a not able change"))


def test_page_header_not_in_raw() -> None:
    r = bad("Check the drive belt.", "Check the drive belt. Page 4")
    assert K.insertion in kinds(r)


def test_ocr_bullet_in_paragraph() -> None:
    assert kinds(bad("¢ Check the belt", "- Check the belt")) == {K.deletion}


def test_plus_minus_sign() -> None:
    r = bad("Gap 0.25 mm ±0.05", "Gap 0.25 mm +0.05")
    assert K.numeric_mismatch in kinds(r)


def _table() -> TableData:
    texts = [
        ["Item", "Size", "Torque"],
        ["Cover bolt", "M8", "35 N·m"],
        ["Fan bolt", "", "6 N·m"],
        ["Pump", "M6", "12 N·m"],
    ]
    cells = [
        TableCell(row=r, col=c, text=t, is_header=r == 0)
        for r, row in enumerate(texts)
        for c, t in enumerate(row)
    ]
    return TableData(n_rows=4, n_cols=3, cells=cells, markdown="")


RAW = "Item | Size | Torque\nCover bolt | M8 | 35 N·m\nFan bolt | 6 N·m\nPump | M6 | 12 N·m"
HEAD = "| Item | Size | Torque |\n|---|---|---|\n"


def test_dropped_table_row() -> None:
    gfm = HEAD + "| Cover bolt | M8 | 35 N·m |\n| Fan bolt |  | 6 N·m |"
    r = bad(RAW, gfm, block_type=BlockType.table, table=_table())
    assert {K.deletion, K.numeric_mismatch} <= kinds(r)
    assert any("12" in v.raw for v in r.violations)


def test_moved_table_cell() -> None:
    gfm = HEAD + "| Cover bolt | M8 | 35 N·m |\n| Fan bolt | 6 N·m |  |\n| Pump | M6 | 12 N·m |"
    r = bad(RAW, gfm, block_type=BlockType.table, table=_table())
    assert kinds(r) & {K.insertion, K.deletion}


def test_rewrite_guard() -> None:
    # quick_ratio < 0.5: the cleanup is a rewrite, reported as one whole-text deletion
    r = bad("Tighten the cover bolts.", "XYZ QJK 1234 !!")
    assert len(r.violations) == 1 and r.violations[0].kind == K.deletion
    assert r.violations[0].raw_start == 0 and r.violations[0].clean_end == len("XYZ QJK 1234 !!")


def test_sorted_violations() -> None:
    r = bad("a 1 b 2 c 3", "a 7 b 8 c 9")
    keys = [
        (
            -1 if v.raw_start is None else v.raw_start,
            -1 if v.clean_start is None else v.clean_start,
            v.kind.value,
        )
        for v in r.violations
    ]
    assert keys == sorted(keys)
