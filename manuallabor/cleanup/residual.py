"""What the deterministic passes could not settle (design 3.1). Pure."""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from manuallabor.cleanup.rules import DetResult, is_item_start
from manuallabor.cleanup.types import LLM_TYPES, ResidualReason
from manuallabor.contracts.block import Block
from manuallabor.scoring.text import cmp_tokens

_SENTENCE_END: Final = re.compile(r"[.:;!?)]$")


def mid_sentence_break(text: str) -> bool:
    """A kept line that does not end a sentence, followed by one that starts with a lowercase
    letter or a digit and is not a list item."""
    lines = text.split("\n")
    for a, b in zip(lines, lines[1:], strict=False):
        if _SENTENCE_END.search(a.rstrip()):
            continue
        b = b.lstrip()
        if b[:1] and (b[0].islower() or b[0].isdigit()) and not is_item_start(b):
            return True
    return False


def alt_reader_reorders(block: Block) -> bool:
    """Another reader of the block read the same tokens in a different sequence."""
    mine = cmp_tokens(block.raw_text)
    bag = Counter(mine)
    for k in sorted(block.raw_text_by_parser):
        if k == block.raw_source:
            continue
        other = cmp_tokens(block.raw_text_by_parser[k])
        if other != mine and Counter(other) == bag:
            return True
    return False


def residual_reasons(block: Block, det: DetResult, layout_risk: bool) -> list[ResidualReason]:
    if block.type not in LLM_TYPES:
        return []
    out: list[ResidualReason] = []
    if any(d.startswith("drop_ambiguous:") for d in det.dh):
        out.append("ambiguous_hyphen")
    if mid_sentence_break(det.text):
        out.append("mid_sentence_break")
    if layout_risk and alt_reader_reorders(block):
        out.append("reading_order")
    return out
