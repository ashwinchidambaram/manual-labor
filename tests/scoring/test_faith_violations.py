"""Test 12: everything outside the allowed edits is a violation, with exact spans."""

from __future__ import annotations

from manuallabor.contracts.block import FaithfulnessResult, TableCell, TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.enums import FaithViolationKind as K
from manuallabor.scoring.faithfulness import check_faithfulness
from manuallabor.scoring.pipeline import score_block
from tests.scoring.conftest import ctx, make_block

HF = ["Acme X200 Service Manual", "Page 3", "Page 4"]  # footers recorded on pages 3, 4


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
    # quick_ratio < 0.5: the cleanup is a rewrite, reported as one whole-text deletion; the
    # number it added is still compared and reported (module 12 review)
    r = bad("Tighten the cover bolts.", "XYZ QJK 1234 !!")
    assert len(r.violations) == 2
    dels = [v for v in r.violations if v.kind == K.deletion]
    nums = [v for v in r.violations if v.kind == K.numeric_mismatch]
    assert len(dels) == 1 and len(nums) == 1
    assert dels[0].raw_start == 0 and dels[0].raw_end == len("Tighten the cover bolts.")
    assert dels[0].clean_start == 0 and dels[0].clean_end == len("XYZ QJK 1234 !!")
    assert nums[0].raw_start is None and nums[0].clean == "1234"


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


# -- AE3 header/footer removal may never delete a numeric body line (module 3 review) --------


def test_hf_template_does_not_delete_other_document_number() -> None:
    """Header TM 5-3895-332-12 recorded; the body line TM 9-2320-280-20 is a reference to
    another manual. Same digit template, different numbers: deleting it is a violation."""
    raw = "Refer to:\nTM 9-2320-280-20\nfor details."
    for page in (None, 8, 9):
        r = bad(raw, "Refer to: for details.", hf_strings=["TM 5-3895-332-12"], page=page)
        assert K.deletion in kinds(r)
        assert any("9-2320-280-20" in v.raw for v in r.violations)


def test_hf_template_page_number_must_be_this_page() -> None:
    raw = "Set gap to\nPage 35\nmm"
    for page in (None, 3, 36):
        r = bad(raw, "Set gap to mm", page=page)
        assert K.deletion in kinds(r) and any("35" in v.raw for v in r.violations)


def test_hf_numeric_line_deletion_queues_block() -> None:
    raw = "Refer to:\nTM 9-2320-280-20\nfor details."
    b = make_block(raw, page=8, clean_text="Refer to: for details.")
    s = score_block(b, ctx(hf_strings=["TM 5-3895-332-12"]), threshold=0.85)
    assert s.faithfulness is not None and not s.faithfulness.passed
    assert s.confidence == 0.0 and s.status == "queued"


# -- uncovered branches named by the review -------------------------------------------------


def test_size_guard_reports_one_whole_text_deletion() -> None:
    from manuallabor.scoring.types import FAITH_MAX_CHARS

    raw = "Check the drive belt for wear.\n" * (FAITH_MAX_CHARS // 50)
    clean = raw.replace("wear", "tear", 1)
    assert len(raw) + len(clean) > FAITH_MAX_CHARS
    r = check_faithfulness(raw, clean)
    assert not r.passed and len(r.violations) == 1
    v = r.violations[0]
    assert v.kind == K.deletion and (v.raw_start, v.raw_end) == (0, len(raw))
    assert (v.clean_start, v.clean_end) == (0, len(clean))
    assert len(r.diff) == 1 and not r.diff[0].allowed
    # identical oversized text passes without alignment
    same = check_faithfulness(raw, raw)
    assert same.passed and [op.op.value for op in same.diff] == ["equal"]
    # an oversized whitespace-only cleanup still passes (canonical forms are equal)
    assert check_faithfulness(raw, " ".join(raw.split())).passed


def _pipe_table() -> TableData:
    texts = [["Signal", "Pins"], ["A|B select", "3"], ["Ground", "4"]]
    cells = [
        TableCell(row=r, col=c, text=t, is_header=r == 0)
        for r, row in enumerate(texts)
        for c, t in enumerate(row)
    ]
    return TableData(n_rows=3, n_cols=2, cells=cells, markdown="")


PIPE_RAW = "Signal | Pins\nA|B select | 3\nGround | 4"


def test_escaped_pipe_in_gfm_cell_passes() -> None:
    gfm = "| Signal | Pins |\n|---|---|\n| A\\|B select | 3 |\n| Ground | 4 |"
    r = check_faithfulness(PIPE_RAW, gfm, block_type=BlockType.table, table=_pipe_table())
    assert r.passed, r.violations


def test_unescaped_pipe_in_gfm_cell_fails() -> None:
    gfm = "| Signal | Pins |\n|---|---|\n| A|B select | 3 |\n| Ground | 4 |"
    bad(PIPE_RAW, gfm, block_type=BlockType.table, table=_pipe_table())
