"""Machine status and the review queue order (design 6)."""

from __future__ import annotations

from collections.abc import Iterable

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType

HF_TYPES = frozenset({BlockType.header, BlockType.footer})


def assign_status(
    confidence: float | None, has_numeric_spec: bool, threshold: float
) -> BlockStatus:
    """auto_approved iff confidence >= threshold and the block carries no numeric spec."""
    if confidence is not None and confidence >= threshold and not has_numeric_spec:
        return BlockStatus.auto_approved
    return BlockStatus.queued


def build_queue(scored: Iterable[Block]) -> list[str]:
    """Queued body blocks (figures included), worst first; None confidence first; ties by id."""
    items = [b for b in scored if b.status == BlockStatus.queued and b.type not in HF_TYPES]
    items.sort(
        key=lambda b: (
            -1.0 if b.confidence is None else b.confidence,
            ids.block_sort_key(b.id),
        )
    )
    return [b.id for b in items]
