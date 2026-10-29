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


# -- unit lexicon and false positives (module 3 review probes) ---------------------------------

SHOULD_FIRE = [
    # the reviewer's probe list, should-fire half
    "Allow 5 min to cool",
    "wait 2 h",
    "Torque to 35 N·m",
    "FSN 3895-443-4696",
    "in 5 s",
    "at 3 m/s",
    "100 ft.lb.",
    # the real manual (TM 5-3895-332-12) spec lines
    "Bore 12,000 in. dia.",
    "Stroke (compression) 13.968 in.",
    "Piston displacement 1580 cu. in.",
    "Rated striking energy 21,000 ft.lb./blow",
    "At 57 p.s.i air gauge pressure at 83 blows per min.",
    "observed on gauge 57 P.S.I.= 21,000 ft.1b. and",
    "Fuel tank 24 gals.",
    "Lubricating oil tank 11 gals.",
    "Depth 25.750 inches",
    "Weight 10,000 pounds",
    "bearing will be 105 tons.",
    "Operation (0° to 126°F)",
    "This manual covers only the MKT Model DA35",
    "Serial Numbers 691201 thru 691209",
    # the lexicon, abbreviations and plurals
    "Supply 24 volts",
    "Rated 12 VDC",
    "Rated 24 VAC",
    "Draws 15 amps",
    "Rated 60 watts",
    "Coil resistance 10 ohms",
    "Line frequency 60 Hz",
    "A 5 inch hose",
    "A 1/2 in. hose",
    'Cut it 12" long',
    "Lift 10 feet",
    "Lift 6 ft.",
    "Torque to 35 ft-lb",
    "Torque to 35 ft·lb",
    "Torque to 40 lb-ft",
    "Torque to 35 Nm",
    "Weighs 5 lb",
    "Weighs 6 lbs.",
    "Inflate to 100 psi",
    "Inflate to 200 kPa",
    "Inflate to 2 bar",
    "Add 5 gallons",
    "Add 5 gal",
    "Add 4 qts",
    "Add 2 qt.",
    "Add 3 liters",
    "Heat to 40 °C",
    "Turn 90 degrees",
    "Idle at 1800 rpm",
    "Rated 40 bpm",
    "Service every 500 hours",
    "Service every 8 hrs",
    "Engine 250 cc",
    "Engine 105 cu in",
    "Duty cycle 10%",
    "Gap 0.25 mm ±0.05",
    "Order P/N 4471-A",
    "NSN 2815-00-123-4567",
    "Serial No. 691201",
]

SHOULD_NOT_FIRE = [
    # the reviewer's probe list, should-not-fire half
    "Page 2",
    "Figure 3",
    "see Figure 4 for details",
    "Section 1.1 General",
    "Printed in 1970",
    "Remove the 4 screws and the cover.",
    "There are 3 steps in this procedure.",
    "Repeat 2 times.",
    "See paragraph 2-4 in chapter 3.",
    "Refer to 3 in the list",
    "Introduced in the 1970s.",
    "Step 1 of 5",
    "Table 2-1. Tools",
    "Item 12 in Figure 4-3",
    "Fig. 3",
    "1.1 General Precautions",
    "Model X200",
    "Use 2 bolts",
    "Check 3 points",
    "Do it 2 or 3 times a day",
    "page 4 in section 2",
    # false positives on the real manual: appendix page refs, roman numerals, OCR garbage
    "A-1",
    "APPENDIX B-1",
    "C-12",
    "Section IV. TROUBLESHOOTING",
    "Section 1V. TROUBLESHOOTING",
    "nett ARPT 5s a ic eer i ee iin eee eines cee 3-2",
    "rN 0G i SA III aise So sp Si arreeccsanamoasannniaeeenees coe 4-2",
    "2-2. Drive cap and cushion block, removal and installation = SSS es 50S be",
    "REFERENCES -_-__-. ee ee",
    "THE MODEL COVERED BY THIS MANUAL",
    "Hold 2 in each hand",
    'Set "35" now',
]


@pytest.mark.parametrize("text", SHOULD_FIRE)
def test_lexicon_fires(text: str) -> None:
    assert find_numeric_specs(text, PM), text


@pytest.mark.parametrize("text", SHOULD_NOT_FIRE)
def test_lexicon_false_positives(text: str) -> None:
    assert find_numeric_specs(text, PM) == [], (text, find_numeric_specs(text, PM))


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("Bore 12,000 in. dia.", "12,000 in."),
        ("Fuel tank 24 gals.", "24 gals."),
        ("Weight 10,000 pounds", "10,000 pounds"),
        ("at 83 blows per min.", "83 blows per min."),
        ("1580 cu. in.", "1580 cu. in."),
        ("Torque 100 ft.lb.", "100 ft.lb."),
    ],
)
def test_lexicon_spans(text: str, spec: str) -> None:
    assert spec in find_numeric_specs(text, None)
