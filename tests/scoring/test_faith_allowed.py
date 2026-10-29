"""Test 11: every allowed edit AE1-AE6 passes, alone and combined."""

from __future__ import annotations

import unicodedata

import pytest

from manuallabor.contracts.block import FaithfulnessResult, TableCell, TableData
from manuallabor.contracts.enums import BlockType, DiffOpKind
from manuallabor.scoring.faithfulness import check_faithfulness

HF = ["Acme X200 Service Manual", "Page 3"]


def ok(raw: str, clean: str, **kw) -> FaithfulnessResult:  # type: ignore[no-untyped-def]
    r = check_faithfulness(raw, clean, hf_strings=kw.pop("hf_strings", HF), **kw)
    assert r.passed, [(v.kind.value, v.raw, v.clean) for v in r.violations]
    assert r.violations == []
    assert all(op.allowed for op in r.diff)
    return r


def test_raw_to_raw() -> None:
    raw = "• Tighten to 35 N·m\nusing the adjust-\nment tool.\nPage 7"
    r = ok(raw, raw)
    assert r.alignment_ratio == 1.0
    assert [op.op for op in r.diff] == [DiffOpKind.equal]


def test_ae1_whitespace() -> None:
    raw = "Check the  drive belt\nfor wear.\n\nReplace it if worn."
    ok(raw, "Check the drive belt for wear. Replace it if worn.")
    ok(raw, "  Check the drive belt\n\nfor wear.\tReplace it if worn.  ")
    ok("Torque: 35 N·m", "Torque:35 N·m")  # a space next to punctuation may go
    ok("Torque:35 N·m", "Torque: 35 N·m")  # or come


def test_ae2_dehyphenation_drop_and_keep() -> None:
    raw = "Use the adjust-\nment screw."
    ok(raw, "Use the adjustment screw.")
    ok(raw, "Use the adjust-ment screw.")
    ok(raw, "Use the adjust-\nment screw.")


def test_ae3_header_footer_exact_and_key() -> None:
    raw = "Acme X200 Service Manual\nCheck the drive belt.\nPage 7"
    ok(raw, "Check the drive belt.")  # exact header + hf_key footer (Page 7 ~ Page 3)
    ok(raw, raw)  # clean may keep them
    ok(raw, "Acme X200 Service Manual Check the drive belt. Page 7")  # kept, joined inline
    ok(raw, "Check the drive belt. Page 7")


def test_ae4_bullets() -> None:
    ok("• Check the belt\n• Replace it", "- Check the belt\n- Replace it")
    ok("* Check the belt", "• Check the belt")
    ok(
        "¢ Check the belt\n¢ Replace it",
        "- Check the belt\n- Replace it",
        block_type=BlockType.list,
    )
    ok("o Check the belt", "• Check the belt", block_type=BlockType.list)


def test_ae5_glyph_identity() -> None:
    ok("eﬃcient ﬁlter", "efficient filter")
    ok("10 mm and 5 V", "10 mm and 5 V")
    ok("adjust­ment", "adjustment")
    ok(unicodedata.normalize("NFD", "Köln café"), unicodedata.normalize("NFC", "Köln café"))


def _table() -> TableData:
    texts = [["Item", "Size", "Torque"], ["Cover bolt", "M8", "35 N·m"], ["Fan bolt", "", "6 N·m"]]
    cells = [
        TableCell(row=r, col=c, text=t, is_header=r == 0)
        for r, row in enumerate(texts)
        for c, t in enumerate(row)
    ]
    return TableData(n_rows=3, n_cols=3, cells=cells, markdown="")


TABLE_RAW = "Item | Size | Torque\nCover bolt | M8 | 35 N·m\nFan bolt | 6 N·m"


def test_ae6_gfm_table() -> None:
    gfm = (
        "| Item | Size | Torque |\n|---|---|---|\n| Cover bolt | M8 | 35 N·m |\n"
        "| Fan bolt |  | 6 N·m |"
    )
    ok(TABLE_RAW, gfm, block_type=BlockType.table, table=_table())
    ok(
        TABLE_RAW,
        gfm.replace("|---|---|---|", "| :--- | ---: | --- |"),
        block_type=BlockType.table,
        table=_table(),
    )


def test_ae6_text_table() -> None:
    ok(TABLE_RAW, TABLE_RAW.replace("\n", "\n "), block_type=BlockType.table, table=_table())


def test_combined() -> None:
    raw = (
        "Acme X200 Service Manual\n"
        "• Remove the cover and ad-\njust the eﬃcient belt tension\n"
        "• Tighten to 35 N·m.\nPage 9"
    )
    clean = "- Remove the cover and adjust the efficient belt tension\n- Tighten to 35 N·m."
    ok(raw, clean)


@pytest.mark.parametrize("raw", ["", " ", "\n\n", "x"])
def test_trivial(raw: str) -> None:
    ok(raw, raw)
