"""Read-only hook to the learned cleanup state (design 7). Module 7 owns the writer.

Only lossless rule kinds are admitted (hyphen exceptions, extra AE4 bullet glyphs); learning
can never widen header/footer removal (AE3)."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Final

from pydantic import ValidationError

from manuallabor.cleanup.types import FEW_SHOT_K, FewShotExample, LearnedCleanup, LearnedRule
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.io import read_json
from manuallabor.project import ProjectPaths
from manuallabor.scoring.faithfulness import BULLETS

log = logging.getLogger(__name__)

_HYPHEN_VALUE: Final = re.compile(r"^[^\W\d_]+-[^\W\d_]+$")
OCR_SOURCES: Final = frozenset({"ocr", "ocr_alt"})


def admit(rule: LearnedRule) -> bool:
    """A rule is used only if it is enabled and its value is valid for its kind."""
    if not rule.enabled:
        return False
    if rule.kind in ("hyphen_keep", "hyphen_drop"):
        ok = _HYPHEN_VALUE.match(rule.value) is not None
    else:
        ok = len(rule.value) == 1 and rule.value in BULLETS
    if not ok:
        log.warning(
            "learned cleanup rule %s ignored: invalid %s value %r", rule.id, rule.kind, rule.value
        )
    return ok


def load_learned_cleanup(paths: ProjectPaths, config: ProjectConfig) -> LearnedCleanup | None:
    """None when learning is off, no snapshot exists, or it is unreadable (logged). Otherwise
    the snapshot with only its admitted rules."""
    if not config.learning.enabled:
        return None
    path = paths.learned_cleanup
    if not path.is_file():
        return None
    try:
        lc = read_json(path, LearnedCleanup)
    except (ValidationError, ValueError, OSError) as exc:
        log.warning("learned cleanup snapshot %s is unreadable, using baseline: %s", path, exc)
        return None
    rules = sorted((r for r in lc.rules if admit(r)), key=lambda r: r.id)
    return lc.model_copy(update={"rules": rules})


def select_examples(
    examples: Sequence[FewShotExample],
    block: Block,
    residual: Sequence[str],
    k: int = FEW_SHOT_K,
) -> list[FewShotExample]:
    """The k nearest examples: same block type, same OCR-ness, most shared residual reasons,
    closest raw length, then id."""
    ocr = block.raw_source in OCR_SOURCES
    res = set(residual)

    def key(ex: FewShotExample) -> tuple[bool, bool, int, int, str]:
        return (
            ex.block_type != block.type,
            ex.ocr != ocr,
            -len(res & set(ex.residual)),
            abs(len(ex.raw) - len(block.raw_text)),
            ex.id,
        )

    return sorted(examples, key=key)[:k]
