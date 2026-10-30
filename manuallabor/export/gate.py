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
    flag_seq: Mapping[str, int] | None = None,
) -> Gate:
    """`blocks_by_doc` carry the human overlay. A block blocks when it is `queued` or `flagged`
    in scope, or when an open flag targets it (a figure flag targets its figure block).

    Coverage (design 11 P3): a blanket override (no target, no flag) covers every blocker. A
    flag override covers that flag (and the blocking status of the block it targets). A target
    override covers the block's blocking status and only the flags that were already open when
    it was recorded: a flag raised on the block afterwards makes it a blocker again. "Afterwards"
    compares the flag's creating action id (`flag_seq`, flag id -> `created_action_id`) with the
    override's action id; without a sequence for a flag, the wall clock decides, and a flag
    stamped at or after the override's time counts as raised after it.
    """
    block_of_figure = {
        str(b.figure_id): b.id for blocks in blocks_by_doc.values() for b in blocks if b.figure_id
    }
    in_scope = {b for s in scope_by_doc.values() for b in s}
    status = {b.id: b.status for blocks in blocks_by_doc.values() for b in blocks}
    order = {b.id: (doc, b.reading_order) for doc, blocks in blocks_by_doc.items() for b in blocks}
    seq = flag_seq or {}

    open_flag_of: dict[str, str] = {}
    flags_of: dict[str, list[Flag]] = {}
    open_flags = 0
    for f in flags:
        if f.status != FlagStatus.open:
            continue
        bid = block_of_figure.get(f.target_id, f.target_id)
        if bid not in in_scope:
            continue
        open_flags += 1
        open_flag_of.setdefault(bid, f.id)
        flags_of.setdefault(bid, []).append(f)

    queued_ids = {b for b in in_scope if status.get(b) == BlockStatus.queued}
    raw = {b for b in in_scope if status.get(b) in BLOCKING} | set(open_flag_of)

    ordered = sorted(overrides, key=lambda o: o.action_id)
    covered: dict[str, ActiveOverride] = {}
    for b in raw:
        bflags = flags_of.get(b, [])
        used: list[ActiveOverride] = []
        ok = True
        if status.get(b) in BLOCKING:
            hits = [ov for ov in ordered if _covers_status(ov, b, bflags, block_of_figure)]
            ok = bool(hits)
            used += hits
        for f in bflags:
            if not ok:
                break
            hits = [ov for ov in ordered if _covers_flag(ov, b, f, seq, block_of_figure)]
            ok = bool(hits)
            used += hits
        if ok and used:
            covered[b] = max(used, key=lambda o: o.action_id)  # the latest covering override
    blockers = sorted((b for b in raw if b not in covered), key=lambda b: order.get(b, ("", 0)))
    return Gate(
        unlocked=not raw,
        open_flags=open_flags,
        queued=len(queued_ids),
        blockers=blockers,
        covered=covered,
        open_flag_of=open_flag_of,
    )


def _blanket(ov: ActiveOverride) -> bool:
    return ov.target_id is None and ov.flag_id is None


def _targets(ov: ActiveOverride, block_id: str, block_of_figure: Mapping[str, str]) -> bool:
    return ov.target_id is not None and block_of_figure.get(ov.target_id, ov.target_id) == block_id


def _covers_status(
    ov: ActiveOverride, block_id: str, flags: Sequence[Flag], block_of_figure: Mapping[str, str]
) -> bool:
    """The block's own `queued`/`flagged` state."""
    if _blanket(ov) or _targets(ov, block_id, block_of_figure):
        return True
    return ov.flag_id is not None and any(f.id == ov.flag_id for f in flags)


def _covers_flag(
    ov: ActiveOverride,
    block_id: str,
    flag: Flag,
    seq: Mapping[str, int],
    block_of_figure: Mapping[str, str],
) -> bool:
    """One open flag on the block."""
    if _blanket(ov) or ov.flag_id == flag.id:
        return True
    if not _targets(ov, block_id, block_of_figure):
        return False
    created = seq.get(flag.id)
    if created is not None:
        return created < ov.action_id
    return flag.created_at < ov.ts
