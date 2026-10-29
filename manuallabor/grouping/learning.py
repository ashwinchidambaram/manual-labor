"""Read-only hook to the learned grouping state (design §7.2). Module 7 owns the writer."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from manuallabor.contracts._base import BlockId, ContractModel, DocSlug
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.io import read_json
from manuallabor.grouping.types import GroupingError
from manuallabor.project import ProjectPaths

BASELINE = "baseline"


class RegroupExample(ContractModel):
    doc_id: DocSlug
    summary: str
    from_title: str
    to_title: str
    kind: Literal["move", "rename"]


class LearnedGrouping(ContractModel):
    snapshot: str
    examples: list[RegroupExample] = []
    do_not_merge: list[tuple[BlockId, BlockId]] = []


def load_learned_grouping(paths: ProjectPaths, config: ProjectConfig) -> LearnedGrouping | None:
    """None when learning is off or no snapshot exists."""
    if not config.learning.enabled:
        return None
    path = paths.learned_grouping
    if not path.is_file():
        return None
    try:
        return read_json(path, LearnedGrouping)
    except (ValidationError, ValueError) as exc:
        raise GroupingError(f"{path}: learned grouping snapshot is invalid: {exc}") from exc


def pick_examples(learned: LearnedGrouping | None, doc_id: str, limit: int) -> list[dict[str, str]]:
    """Up to `limit` examples: this document's first, then the most recent (last in file)."""
    if learned is None:
        return []
    mine = [e for e in reversed(learned.examples) if e.doc_id == doc_id]
    rest = [e for e in reversed(learned.examples) if e.doc_id != doc_id]
    return [e.model_dump(mode="json") for e in (mine + rest)[:limit]]
