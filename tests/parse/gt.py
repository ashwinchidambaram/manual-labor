"""Ground-truth helpers shared by the parse tests."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from manuallabor.contracts.block import Block
from manuallabor.parse.geometry import iou

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TOKEN = re.compile(r"[^\s|•]+")
PDF_FIXTURES = ("clean", "twocol", "tables", "figures", "scanned")
BORN_DIGITAL = ("clean", "twocol", "tables", "figures")


def load_gt(stem: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "ground_truth" / f"{stem}.json").read_text())


def gt_text(b: dict[str, Any]) -> str:
    return "\n".join(b["raw_lines"])


def tokens(s: str) -> list[str]:
    return TOKEN.findall(s)


def f1_counts(pred: list[str], ref: list[str]) -> tuple[int, int, int]:
    """(true positives, n_pred, n_ref) for multiset token overlap."""
    common = Counter(pred) & Counter(ref)
    return sum(common.values()), len(pred), len(ref)


def f1(tp: int, n_pred: int, n_ref: int) -> float:
    if n_pred == 0 and n_ref == 0:
        return 1.0
    if tp == 0:
        return 0.0
    p, r = tp / n_pred, tp / n_ref
    return 2 * p * r / (p + r)


def match_blocks(
    gt_blocks: list[dict[str, Any]], blocks: list[Block], min_iou: float = 0.5
) -> dict[int, Block]:
    """GT index -> parsed block; greedy by descending IoU, one-to-one, same page."""
    pairs: list[tuple[float, int, str]] = []
    by_id = {b.id: b for b in blocks}
    for gi, g in enumerate(gt_blocks):
        for b in blocks:
            if b.page != g["page"] or b.bbox is None:
                continue
            v = iou(g["bbox"], b.bbox)
            if v >= min_iou:
                pairs.append((-v, gi, b.id))
    pairs.sort()
    out: dict[int, Block] = {}
    used: set[str] = set()
    for _, gi, bid in pairs:
        if gi in out or bid in used:
            continue
        out[gi] = by_id[bid]
        used.add(bid)
    return out
