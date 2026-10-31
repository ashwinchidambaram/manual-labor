"""The export gate and override coverage (design 11 P2, P3, section 14). Pure."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType, FlagStatus
from manuallabor.contracts.flag import Flag
from manuallabor.export.types import ActiveOverride

__all__ = ["COUNT_KEYS", "Gate", "export_gate"]

BLOCKING = (BlockStatus.queued, BlockStatus.flagged)
HF = (BlockType.header, BlockType.footer)
# the buckets of `Gate.counts`: every in-scope body block is in exactly one of auto_approved,
# approved, edited, rejected, overridden, to_review and flagged; `blocking` is to_review + flagged
# (design 11 sections 14 and 17)
COUNT_KEYS = (
    "in_scope",
    "auto_approved",
    "approved",
    "edited",
    "rejected",
    "overridden",
    "blocking",
    "to_review",
    "flagged",
)


@dataclass
class Gate:
    unlocked: bool  # raw: no open flag and no queued block in scope
    open_flags: int
    queued: int
    blockers: list[str]  # blocks no active override covers, in reading order per document
    covered: dict[str, ActiveOverride] = field(default_factory=dict)  # block id -> override
    open_flag_of: dict[str, str] = field(default_factory=dict)  # block id -> its open flag id
    # every open flag no override covers, with its block, in the blockers' order
    flag_blockers: list[tuple[Flag, str]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # COUNT_KEYS -> n

    @property
    def allowed(self) -> bool:
        return not self.blockers


def export_gate(
    blocks_by_doc: Mapping[str, Sequence[Block]],
    scope_by_doc: Mapping[str, set[str]],
    flags: Iterable[Flag],
    overrides: Sequence[ActiveOverride],
) -> Gate:
    """`blocks_by_doc` carry the human overlay. The scope is the in-scope body blocks: a page
    header or footer is never exported (P4), so it neither blocks nor counts. A block blocks
    when it is `queued` or `flagged`, or when an open flag targets it (a figure flag targets its
    figure block).

    Coverage (design 11 P3, amended in section 14): a blanket override (no target, no flag)
    covers every blocker. A flag override covers that flag and the review state of the block it
    targets. A block override covers the block's review state only, never an open flag on it,
    whichever was recorded first: a flag is the reviewer saying "this may be wrong", and only a
    decision that names the flag may export the block anyway.
    """
    block_of_figure = {
        str(b.figure_id): b.id for blocks in blocks_by_doc.values() for b in blocks if b.figure_id
    }
    by_id = {b.id: b for blocks in blocks_by_doc.values() for b in blocks}
    in_scope = {
        b for s in scope_by_doc.values() for b in s if b in by_id and by_id[b].type not in HF
    }
    status = {b: by_id[b].status for b in in_scope}
    order = {b.id: (doc, b.reading_order) for doc, blocks in blocks_by_doc.items() for b in blocks}

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

    queued_ids = {b for b in in_scope if status[b] == BlockStatus.queued}
    raw = {b for b in in_scope if status[b] in BLOCKING} | set(open_flag_of)

    ordered = sorted(overrides, key=lambda o: o.action_id)
    covered: dict[str, ActiveOverride] = {}
    uncovered_flags: dict[str, list[Flag]] = {}
    for b in raw:
        bflags = flags_of.get(b, [])
        used: list[ActiveOverride] = []
        ok = True
        if status[b] in BLOCKING:
            hits = [ov for ov in ordered if _covers_status(ov, b, bflags, block_of_figure)]
            ok = bool(hits)
            used += hits
        for f in bflags:
            hits = [ov for ov in ordered if _covers_flag(ov, f)]
            if not hits:
                ok = False
                uncovered_flags.setdefault(b, []).append(f)
            used += hits
        if ok and used:
            covered[b] = max(used, key=lambda o: o.action_id)  # the latest covering override
    blockers = sorted((b for b in raw if b not in covered), key=lambda b: order.get(b, ("", 0)))
    flag_blockers = [
        (f, b) for b in blockers for f in sorted(uncovered_flags.get(b, []), key=lambda f: f.id)
    ]

    counts = dict.fromkeys(COUNT_KEYS, 0)
    counts["in_scope"] = len(in_scope)
    for b in in_scope:
        if b in raw:
            if b in covered:
                counts["overridden"] += 1
            else:
                counts["blocking"] += 1
                # held by a flag no override covers, else waiting for a person's review
                held = b in uncovered_flags or status[b] == BlockStatus.flagged
                counts["flagged" if held else "to_review"] += 1
        else:
            counts[status[b].value] += 1
    return Gate(
        unlocked=not raw,
        open_flags=open_flags,
        queued=len(queued_ids),
        blockers=blockers,
        covered=covered,
        open_flag_of=open_flag_of,
        flag_blockers=flag_blockers,
        counts=counts,
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


def _covers_flag(ov: ActiveOverride, flag: Flag) -> bool:
    """One open flag: only a blanket override or the override naming it."""
    return _blanket(ov) or ov.flag_id == flag.id
