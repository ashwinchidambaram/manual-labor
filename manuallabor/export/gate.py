"""The export gate and override coverage (design 11 P2, P3). Pure."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, FlagStatus
from manuallabor.contracts.flag import Flag
from manuallabor.export.types import ActiveOverride

__all__ = ["Gate", "export_gate"]

BLOCKING = (BlockStatus.queued, BlockStatus.flagged)


@dataclass
class Gate:
    unlocked: bool  # raw: no open flag and no queued block in scope
    open_flags: int
    queued: int
    blockers: list[str]  # blocks no active override covers, in reading order per document
    covered: dict[str, ActiveOverride] = field(default_factory=dict)  # block id -> override
    open_flag_of: dict[str, str] = field(default_factory=dict)  # block id -> its open flag id

    @property
    def allowed(self) -> bool:
        return not self.blockers


def export_gate(
    blocks_by_doc: Mapping[str, Sequence[Block]],
    scope_by_doc: Mapping[str, set[str]],
    flags: Iterable[Flag],
    overrides: Sequence[ActiveOverride],
) -> Gate:
    """`blocks_by_doc` carry the human overlay. A block blocks when it is `queued` or `flagged`
    in scope, or when an open flag targets it (a figure flag targets its figure block)."""
    block_of_figure = {
        str(b.figure_id): b.id for blocks in blocks_by_doc.values() for b in blocks if b.figure_id
    }
    in_scope = {b for s in scope_by_doc.values() for b in s}
    status = {b.id: b.status for blocks in blocks_by_doc.values() for b in blocks}
    order = {b.id: (doc, b.reading_order) for doc, blocks in blocks_by_doc.items() for b in blocks}

    open_flag_of: dict[str, str] = {}
    open_flags = 0
    for f in flags:
        if f.status != FlagStatus.open:
            continue
        bid = block_of_figure.get(f.target_id, f.target_id)
        if bid not in in_scope:
            continue
        open_flags += 1
        open_flag_of.setdefault(bid, f.id)

    queued_ids = {b for b in in_scope if status.get(b) == BlockStatus.queued}
    raw = {b for b in in_scope if status.get(b) in BLOCKING} | set(open_flag_of)

    covered: dict[str, ActiveOverride] = {}
    for ov in sorted(overrides, key=lambda o: o.action_id):
        for b in raw:
            if _covers(ov, b, open_flag_of.get(b), block_of_figure):
                covered[b] = ov  # the latest covering override wins
    blockers = sorted((b for b in raw if b not in covered), key=lambda b: order.get(b, ("", 0)))
    return Gate(
        unlocked=not raw,
        open_flags=open_flags,
        queued=len(queued_ids),
        blockers=blockers,
        covered=covered,
        open_flag_of=open_flag_of,
    )


def _covers(
    ov: ActiveOverride, block_id: str, flag_id: str | None, block_of_figure: Mapping[str, str]
) -> bool:
    if ov.target_id is None and ov.flag_id is None:
        return True
    if ov.target_id is not None:
        tgt = block_of_figure.get(ov.target_id, ov.target_id)
        if tgt == block_id:
            return True
    return ov.flag_id is not None and ov.flag_id == flag_id
