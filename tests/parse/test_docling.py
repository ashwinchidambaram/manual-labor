"""Test 30: Docling adapter geometry and list merging (reads the parsed project's docling.json)."""

from __future__ import annotations

from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.io import read_json
from manuallabor.parse.types import ParserOutput
from tests.parse.conftest import Parsed
from tests.parse.gt import load_gt


def test_30_docling_bbox_origin_and_lists(parsed: Parsed) -> None:
    out = read_json(parsed.paths.doc("clean").parser_output("docling"), ParserOutput)
    gt = [b for b in load_gt("clean")["blocks"] if b["page"] == 2]
    heading = next(b for b in gt if b["type"] == "heading")
    page2 = out.pages[1].blocks
    cand = next(b for b in page2 if b.kind == BlockType.heading and b.text == heading["text"])
    assert cand.bbox is not None
    assert abs(cand.bbox[1] - heading["bbox"][1]) <= 1.0  # y0 == 72.0 after the origin flip
    gt_lists = [b for b in gt if b["type"] == "list"]
    got_lists = [b for b in page2 if b.kind == BlockType.list]
    assert len(got_lists) == len(gt_lists) == 1
    assert got_lists[0].text.split("\n") == gt_lists[0]["text"].split("\n")
