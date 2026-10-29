"""Caption matching for figures (design section 7). Pure over one document's blocks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.figures.types import CAPTION_MAX_GAP_PT

_SKIP = {BlockType.header, BlockType.footer}
_MIN_GAP = -6.0


@dataclass(frozen=True)
class CaptionMatch:
    block_id: str
    text: str
    trimmed: bool


def trim_caption(raw: str) -> tuple[str, bool]:
    """Keep lines up to the first sentence end followed by an uppercase line start."""
    lines = [ln.strip() for ln in raw.split("\n")]
    lines = [ln for ln in lines if ln]
    keep = len(lines)
    for i in range(len(lines) - 1):
        if lines[i].endswith(".") and lines[i + 1][:1].isupper():
            keep = i + 1
            break
    return " ".join(lines[:keep]), keep < len(lines)


def _x_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > 0


def _is_candidate(fig: Block, cap: Block, *, below: bool) -> bool:
    if cap.type != BlockType.caption:
        return False
    if fig.bbox is None or cap.bbox is None:
        return True  # DOCX: adjacency only
    if cap.page != fig.page:
        return False
    gap = cap.bbox[1] - fig.bbox[3] if below else fig.bbox[1] - cap.bbox[3]
    return _MIN_GAP <= gap <= CAPTION_MAX_GAP_PT and _x_overlap(fig.bbox, cap.bbox)


def find_captions(blocks: Sequence[Block]) -> dict[str, CaptionMatch]:
    seq = sorted(blocks, key=lambda b: b.reading_order)
    body = [b for b in seq if b.type not in _SKIP]
    pos = {b.id: i for i, b in enumerate(body)}
    figs = [b for b in body if b.type == BlockType.figure and b.figure_id]
    claimed: dict[str, str] = {}  # caption block id -> figure id
    result: dict[str, Block] = {}
    for below in (True, False):
        for f in figs:
            assert f.figure_id is not None
            if f.figure_id in result:
                continue
            j = pos[f.id] + (1 if below else -1)
            if not 0 <= j < len(body):
                continue
            cap = body[j]
            if cap.id in claimed or not _is_candidate(f, cap, below=below):
                continue
            claimed[cap.id] = f.figure_id
            result[f.figure_id] = cap
    out: dict[str, CaptionMatch] = {}
    for fid, cap in result.items():
        text, trimmed = trim_caption(cap.raw_text)
        out[fid] = CaptionMatch(cap.id, text, trimmed)
    return out
