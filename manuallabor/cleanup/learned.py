"""Read-only hook to the learned cleanup state (design 7). Module 7 owns the writer.

Only lossless rule kinds are admitted (hyphen exceptions, extra AE4 bullet glyphs); learning
can never widen header/footer removal (AE3)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError

from manuallabor.cleanup.types import FEW_SHOT_K, FewShotExample, LearnedCleanup, LearnedRule
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.project import ProjectPaths
from manuallabor.scoring.faithfulness import BULLETS, check_faithfulness

log = logging.getLogger(__name__)

_HYPHEN_VALUE: Final = re.compile(r"^[^\W\d_]+-[^\W\d_]+$")
OCR_SOURCES: Final = frozenset({"ocr", "ocr_alt"})


def admit(rule: LearnedRule) -> bool:
    """A rule is used only if it is enabled and its value is valid for its kind (an invalid
    value is logged)."""
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


@dataclass(frozen=True)
class LearningRejected:
    """Ids of the learned items that were not admitted (invalid, never merely disabled)."""

    rules: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def _item_id(item: Any, k: int) -> str:
    v = item.get("id") if isinstance(item, dict) else None
    return v if isinstance(v, str) and v else f"#{k}"


def admit_example(ex: FewShotExample) -> bool:
    """A few-shot pair is shown to the model as a correct cleanup, so it must be one: clean
    differs from raw and passes the faithfulness check against it."""
    if ex.clean == ex.raw:
        return False
    return check_faithfulness(ex.raw, ex.clean, block_type=ex.block_type).passed


def load_learned_cleanup_ex(
    paths: ProjectPaths, config: ProjectConfig
) -> tuple[LearnedCleanup | None, LearningRejected]:
    """The snapshot with only its admitted rules and examples, and the ids of the rejected
    ones. Each rule and example is validated on its own: an invalid one is rejected (and
    logged), the rest still apply. None when learning is off, no snapshot exists, or the file
    itself is unreadable (not JSON, no snapshot id)."""
    none = LearningRejected()
    if not config.learning.enabled:
        return None, none
    path = paths.learned_cleanup
    if not path.is_file():
        return None, none
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        snapshot = LearnedCleanup.model_validate(
            {"snapshot": data.get("snapshot") if isinstance(data, dict) else None}
        ).snapshot
    except (ValidationError, ValueError, OSError) as exc:
        log.warning("learned cleanup snapshot %s is unreadable, using baseline: %s", path, exc)
        return None, none
    raw_rules = data.get("rules", [])
    raw_examples = data.get("examples", [])
    rules: list[LearnedRule] = []
    examples: list[FewShotExample] = []
    rejected_rules: list[str] = []
    rejected_examples: list[str] = []
    for k, item in enumerate(raw_rules if isinstance(raw_rules, list) else []):
        try:
            rule = LearnedRule.model_validate(item)
        except ValidationError as exc:
            log.warning("learned cleanup rule %s rejected: %s", _item_id(item, k), exc)
            rejected_rules.append(_item_id(item, k))
            continue
        if not rule.enabled:
            continue
        if admit(rule):
            rules.append(rule)
        else:
            rejected_rules.append(rule.id)
    for k, item in enumerate(raw_examples if isinstance(raw_examples, list) else []):
        try:
            ex = FewShotExample.model_validate(item)
        except ValidationError as exc:
            log.warning("learned few-shot example %s rejected: %s", _item_id(item, k), exc)
            rejected_examples.append(_item_id(item, k))
            continue
        if admit_example(ex):
            examples.append(ex)
        else:
            log.warning("learned few-shot example %s rejected: not a faithful cleanup", ex.id)
            rejected_examples.append(ex.id)
    lc = LearnedCleanup(
        snapshot=snapshot,
        rules=sorted(rules, key=lambda r: r.id),
        examples=examples,
    )
    return lc, LearningRejected(sorted(rejected_rules), sorted(rejected_examples))


def load_learned_cleanup(paths: ProjectPaths, config: ProjectConfig) -> LearnedCleanup | None:
    """``load_learned_cleanup_ex`` without the rejected ids."""
    return load_learned_cleanup_ex(paths, config)[0]


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
