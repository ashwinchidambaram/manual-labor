"""A `table_structure` flag only on a table block (design 08 section 12; first-time user run 5:
a list block flagged "Table structure" got an engineer's refusal from the agent pass)."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockType
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp
from manuallabor.state.models import FlagIn, ReviewActionIn
from tests.state.helpers import Env


def _flag(env: Env, block_id: str, category: str) -> object:
    return env.review.act(
        ReviewActionIn(
            kind="flag",
            block_id=block_id,
            flag=FlagIn(category=category, note=None),  # type: ignore[arg-type]
            request_id=env.rid(),
        )
    )


def test_table_structure_is_refused_on_a_block_that_is_not_a_table(lp: ProjectPaths) -> None:
    env = Env(lp)
    try:
        items = env.review.queue(None, None, None, 200, 0).items
        other = next(i for i in items if i.type != BlockType.table.value)
        with pytest.raises(InvalidOp, match="Table structure applies to table blocks"):
            _flag(env, other.block_id, "table_structure")
        assert env.store.flags() == []
        _flag(env, other.block_id, "wrong_text")  # the category it should have been
        table = next((i for i in items if i.type == BlockType.table.value), None)
        if table is not None:
            _flag(env, table.block_id, "table_structure")
    finally:
        env.close()
