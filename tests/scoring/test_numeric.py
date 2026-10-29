"""Test 9: has_numeric_spec rules, the table rule, the reader union, and GT recall."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuallabor.contracts.block import TableCell, TableData
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.numeric import FAITH_NUM_RE, find_numeric_specs, numeric_specs_for
from tests.parse.gt import match_blocks
from tests.scoring.conftest import Scored, make_block

PM = "Acme X200"


@pytest.mark.parametrize(
    "text",
    [
        "Tighten to 35 N·m.",
        "Supply 12 V to the board.",
        "Gap 0.25 mm.",
        "Turn it 90°.",
        "Add 2.5 L of coolant.",
        "Use a 10 A fuse.",
        "Torque 10 to 60 N·m.",
        "Rated 12VDC.",
        "Clearance 0.05 ±0.01",
        "Order P/N 4471-A today.",
        "Part number: AB-1234",
        "Use an M8 bolt.",
        "Connector J1.",
        "Board 120 x 80 inside.",
        "The torque must be kept at 35 always",
        "Pressure: 3 bar",
    ],
)
def test_positive(text: str) -> None:
    assert find_numeric_specs(text, PM), text


@pytest.mark.parametrize(
    "text",
    [
        "1.1 General Precautions",
        "see Figure 3",
        "Page 3",
        "The Acme X200 is a compact unit.",
        "Check the belt for wear.",
        "Step 2. Remove the cover.",
    ],
)
def test_negative(text: str) -> None:
    assert find_numeric_specs(text, PM) == [], text


def test_spec_order_and_dedupe() -> None:
    assert find_numeric_specs("Use M8 at 35 N·m; M8 again.", PM)[:2] == ["M8", "35 N·m"]


def _table(texts: list[list[str]]) -> TableData:
    cells = [
        TableCell(row=r, col=c, text=t, is_header=r == 0)
        for r, row in enumerate(texts)
        for c, t in enumerate(row)
    ]
    return TableData(n_rows=len(texts), n_cols=len(texts[0]), cells=cells, markdown="")


def test_table_rule() -> None:
    t = _table([["Item", "Qty 2"], ["Belt", "1"]])
    b = make_block("Item | Qty 2\nBelt | 1", type=BlockType.table, table=t)
    assert numeric_specs_for(b, PM)[0]
    t = _table([["Item 1", "Note 2"], ["Belt", "check"]])
    b = make_block("Item 1 | Note 2\nBelt | check", type=BlockType.table, table=t)
    assert not numeric_specs_for(b, PM)[0]  # digits only in the header row


def test_union_over_readers() -> None:
    b = make_block(
        "Tighten to 3S N·m.",
        texts={
            "pymupdf": "Tighten to 3S N·m.",
            "docling": "Tighten to 3S N·m.",
            "ocr": "Tighten to 35 N-m.",
        },
    )
    yes, specs = numeric_specs_for(b, PM)
    assert yes and "35 N-m" in specs


def test_header_footer_figure_never() -> None:
    for t in (BlockType.header, BlockType.footer):
        assert not numeric_specs_for(make_block("Page 35 N·m", type=t), PM)[0]


def test_faith_num_re_is_sign_aware() -> None:
    assert FAITH_NUM_RE.findall("±0.05 and +0.05 and 4471-A and 4-18 and M8") == [
        "±0.05",
        "+0.05",
        "4471",
        "4",
        "18",
        "8",
    ]


GT_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ground_truth"


@pytest.mark.parametrize("slug", ["clean", "twocol", "tables"])
def test_gt_recall(scoredproj: Scored, slug: str) -> None:
    gt = json.loads((GT_DIR / f"{slug}.json").read_text())
    blocks = scoredproj.blocks(slug)
    doc = scoredproj.doc(slug)
    gt_blocks = [g for g in gt["blocks"] if not g.get("is_header_footer") and g["type"] != "figure"]
    matched = match_blocks(gt_blocks, blocks)
    tp = fn = fp = 0
    for gi, b in matched.items():
        want = bool(gt_blocks[gi]["has_numeric_spec"])
        got = numeric_specs_for(b, doc.product_model)[0]
        tp += want and got
        fn += want and not got
        fp += got and not want
    recall = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp)
    print(
        f"\n{slug}: has_numeric_spec recall {recall:.3f} precision {precision:.3f} "
        f"(tp {tp}, fn {fn}, fp {fp}, matched {len(matched)}/{len(gt_blocks)})"
    )
    assert tp + fn > 0
    assert recall == 1.0
