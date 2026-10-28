"""User selection of blocks."""

from __future__ import annotations

from typing import Any

from pydantic import field_validator

from manuallabor import ids
from manuallabor.contracts._base import BlockId, ContractModel
from manuallabor.contracts.enums import ArticleSplit, GroupView


class Selection(ContractModel):
    block_ids: list[BlockId]
    article_split: ArticleSplit = ArticleSplit.per_topic
    active_view: GroupView = GroupView.topic

    @field_validator("block_ids", mode="before")
    @classmethod
    def _dedupe_sort(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple, set, frozenset)) and all(isinstance(x, str) for x in v):
            try:
                return sorted(set(v), key=ids.block_sort_key)
            except ValueError:
                return list(v)
        return v
