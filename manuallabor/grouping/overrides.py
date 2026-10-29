"""Human regrouping decisions, always applied (design §7.1)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from manuallabor import ids
from manuallabor.contracts.enums import TitleSource, UnassignedReason
from manuallabor.contracts.group import GroupOverride
from manuallabor.contracts.io import read_json_list
from manuallabor.grouping.types import TITLE_MAX, Assembly, GroupingError
from manuallabor.parse.text import collapse_ws


def load_overrides(path: Path) -> list[GroupOverride]:
    if not Path(path).is_file():
        return []
    try:
        return read_json_list(path, GroupOverride)
    except ValueError as exc:  # pydantic's ValidationError and JSON errors are ValueErrors
        raise GroupingError(f"{path}: invalid group overrides: {exc}") from exc


def apply_overrides(
    asm: Assembly, overrides: Sequence[GroupOverride]
) -> tuple[int, list[int], set[str]]:
    """Apply in `seq` order. Returns (applied count, stale indexes into `overrides`, ids of the
    blocks that were moved). A target that no longer exists makes the override stale: it is
    reported and never applied."""
    by_slug = {slug: key for key, slug in asm.slugs.items()}
    applied = 0
    stale: list[int] = []
    moved: set[str] = set()
    for idx in sorted(range(len(overrides)), key=lambda i: (overrides[i].seq, i)):
        o = overrides[idx]
        if o.kind == "move":
            assert o.block_id is not None and o.to_topic_slug is not None
            if o.block_id not in asm.placed:
                stale.append(idx)
                continue
            if o.to_topic_slug == ids.UNASSIGNED:
                if asm.placed[o.block_id] is not None:
                    asm.placed[o.block_id] = None
                    asm.reasons[o.block_id] = UnassignedReason.low_similarity
            else:
                key = by_slug.get(o.to_topic_slug)
                if key is None:
                    stale.append(idx)
                    continue
                asm.placed[o.block_id] = key
                asm.reasons.pop(o.block_id, None)
            moved.add(o.block_id)
            applied += 1
        else:
            assert o.topic_slug is not None and o.title is not None
            key = by_slug.get(o.topic_slug)
            title = collapse_ws(o.title)[:TITLE_MAX].strip()
            if key is None or not title:
                stale.append(idx)
                continue
            asm.titles[key] = title
            asm.sources[key] = TitleSource.human
            applied += 1
    return applied, sorted(stale), moved
