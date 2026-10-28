"""Header and footer detection (design 01-parse section 6)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from manuallabor.contracts.enums import BlockType
from manuallabor.parse.text import hf_key

BAND_FRACTION = 0.12
MIN_PAGES = 3
JITTER_PT = 8.0
OCR_CLUSTER_RATIO = 0.85


@dataclass(frozen=True)
class HFItem:
    index: int
    page: int
    bbox: Sequence[float]
    text: str
    hint: str | None  # docling "page_header" / "page_footer"
    is_region: bool
    page_height: float
    is_ocr: bool


def _band(it: HFItem) -> str | None:
    if it.bbox[3] <= BAND_FRACTION * it.page_height:
        return "top"
    if it.bbox[1] >= (1.0 - BAND_FRACTION) * it.page_height:
        return "bottom"
    return None


def _cluster_keys(keys: list[str]) -> dict[str, str]:
    """Map every key to a cluster representative (greedy in sorted order)."""
    reps: list[str] = []
    out: dict[str, str] = {}
    for k in sorted(set(keys)):
        for r in reps:
            if SequenceMatcher(None, r, k).ratio() >= OCR_CLUSTER_RATIO:
                out[k] = r
                break
        else:
            reps.append(k)
            out[k] = k
    return out


def detect_headers_footers(items: Sequence[HFItem], n_pages: int) -> dict[int, BlockType]:
    """Return {item.index: header|footer}."""
    result: dict[int, BlockType] = {}
    cands: list[tuple[HFItem, str]] = []
    for it in items:
        if it.is_region or not it.text.strip():
            continue
        band = _band(it)
        if band is None:
            continue
        cands.append((it, band))
        if it.hint == "page_header" and band == "top":
            result[it.index] = BlockType.header
        elif it.hint == "page_footer" and band == "bottom":
            result[it.index] = BlockType.footer
    if n_pages < MIN_PAGES:
        return result
    need = max(MIN_PAGES, math.ceil(0.5 * n_pages))
    for band, btype in (("top", BlockType.header), ("bottom", BlockType.footer)):
        members = [it for it, b in cands if b == band]
        keys = {it.index: hf_key(it.text) for it in members}
        cluster = _cluster_keys(list(keys.values())) if any(it.is_ocr for it in members) else {}
        groups: dict[str, list[HFItem]] = {}
        for it in members:
            k = keys[it.index]
            groups.setdefault(cluster.get(k, k), []).append(it)
        for key in sorted(groups):
            grp = groups[key]
            if len({it.page for it in grp}) < need:
                continue
            centers = [(it.bbox[1] + it.bbox[3]) / 2.0 for it in grp]
            med = statistics.median(centers)
            if all(abs(c - med) <= JITTER_PT for c in centers):
                for it in grp:
                    result[it.index] = btype
    return result
