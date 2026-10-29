"""Block summaries for embedding and naming (design §3.1). Raw text only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.grouping.structure import is_header_footer
from manuallabor.grouping.types import SUMMARY_TOKENS, StructureResult
from manuallabor.parse.text import collapse_ws

PATH_SEP = " > "


def is_no_text(b: Block) -> bool:
    """A body block with nothing to embed (figures are embedded through their caption)."""
    return b.type != BlockType.figure and collapse_ws(b.raw_text) == ""


def bound_captions(blocks: Sequence[Block]) -> dict[str, str]:
    """figure block id -> bound caption block id. The caption is the body block right before
    or right after the figure in reading order on the same page; after wins, and a caption
    binds to at most one figure."""
    body = [b for b in blocks if not is_header_footer(b)]
    body.sort(key=lambda b: (b.reading_order, ids.block_sort_key(b.id)))
    out: dict[str, str] = {}
    taken: set[str] = set()
    for i, b in enumerate(body):
        if b.type != BlockType.figure:
            continue
        for j in (i + 1, i - 1):
            if 0 <= j < len(body):
                c = body[j]
                if c.type == BlockType.caption and c.page == b.page and c.id not in taken:
                    out[b.id] = c.id
                    taken.add(c.id)
                    break
    return out


def block_summaries(
    blocks: Sequence[Block],
    structure: StructureResult,
    captions: Mapping[str, str] | None = None,
    tokens: int = SUMMARY_TOKENS,
) -> dict[str, str]:
    """`"{path}\\n{type}: {first N tokens}"` for every body block."""
    by_id = {b.id: b for b in blocks}
    caps = bound_captions(blocks) if captions is None else captions
    out: dict[str, str] = {}
    for b in blocks:
        if is_header_footer(b):
            continue
        if b.type == BlockType.figure:
            cap = by_id.get(caps.get(b.id, ""))
            text = cap.raw_text if cap is not None else ""
        else:
            text = b.raw_text
        words = collapse_ws(text).split()[:tokens]
        path = PATH_SEP.join(structure.path_of.get(b.id, []))
        out[b.id] = f"{path}\n{b.type.value}: {' '.join(words)}"
    return out
