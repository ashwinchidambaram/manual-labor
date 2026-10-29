"""reading_order_risk: LIS displacement per parser, overlaps, multi-column pages (design 2.5)."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence

from manuallabor.contracts.block import Block, Signal
from manuallabor.contracts.enums import BlockType, SignalName
from manuallabor.scoring.types import RO_DISPLACED, RO_MULTICOL, RO_OVERLAP, clamp01

HF_TYPES = frozenset({BlockType.header, BlockType.footer})


def lis_keep(seq: Sequence[int]) -> list[int]:
    """Positions of one longest non-decreasing subsequence (patience sorting, bisect_right,
    reconstructed from the top of the last pile). Deterministic for ties."""
    tails: list[int] = []  # value at the top of each pile
    tops: list[int] = []  # position of the top of each pile
    prev: list[int] = [-1] * len(seq)
    for i, v in enumerate(seq):
        k = bisect_right(tails, v)
        if k == len(tails):
            tails.append(v)
            tops.append(i)
        else:
            tails[k] = v
            tops[k] = i
        prev[i] = tops[k - 1] if k > 0 else -1
    out: list[int] = []
    i = tops[-1] if tops else -1
    while i != -1:
        out.append(i)
        i = prev[i]
    return out[::-1]


def displaced_blocks(page_blocks: Sequence[Block]) -> dict[str, list[str]]:
    """block id -> sorted parser keys in whose order the block is displaced (one page)."""
    body = sorted((b for b in page_blocks if b.type not in HF_TYPES), key=lambda b: b.reading_order)
    keys = sorted({k for b in body for k in b.order_by_parser})
    out: dict[str, list[str]] = {}
    for k in keys:
        having = [b for b in body if k in b.order_by_parser]
        if len(having) < 2:
            continue
        keep = set(lis_keep([b.order_by_parser[k] for b in having]))
        for pos, b in enumerate(having):
            if pos not in keep:
                out.setdefault(b.id, []).append(k)
    return out


def reading_order_risk(
    displaced_in: Sequence[str], in_overlap: bool, n_columns: int | None
) -> Signal:
    multicol = (n_columns or 0) >= 2
    value = (
        (1 - RO_DISPLACED * bool(displaced_in))
        * (1 - RO_OVERLAP * in_overlap)
        * (1 - RO_MULTICOL * multicol)
    )
    parts = []
    if displaced_in:
        parts.append(f"displaced in {', '.join(displaced_in)} order")
    if in_overlap:
        parts.append("overlaps another block")
    if multicol:
        parts.append(f"page has {n_columns} columns")
    return Signal(
        name=SignalName.reading_order_risk,
        value=clamp01(value),
        critical=False,
        detail="; ".join(parts) if parts else "order agrees; single column",
    )
