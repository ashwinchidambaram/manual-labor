"""Review F6: a selection op stores its delta, not two full snapshots and the whole outcome.

The action log stays replayable both ways: a replayed request returns the response it got the
first time (design 07 S3), even after later ops, and the deltas replayed forward from the first
selection action rebuild the stored selection. Rows written before the change still read."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from manuallabor.contracts.selection import Selection
from manuallabor.project import ProjectPaths
from manuallabor.state.models import ActionKind, SelectionOp, SelectionOut
from manuallabor.state.selection_log import SELECTION_KINDS, replay_selection
from tests.state.helpers import Env


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def _op(env: Env, op: str, **kw: Any) -> SelectionOut:
    return env.scope.apply(SelectionOp(op=op, request_id=env.rid(), **kw))  # type: ignore[arg-type]


def _last_row(env: Env) -> Any:
    return env.store.q1("SELECT * FROM actions ORDER BY id DESC LIMIT 1")


def test_a_single_block_op_stores_a_small_delta_and_no_snapshots(env: Env) -> None:
    sel = env.scope.get().selection.block_ids
    assert len(sel) > 100  # a selection big enough that a snapshot would dominate the row
    _op(env, "deselect", block_ids=[sel[0]])  # the first write: the default selection is new
    _op(env, "select", block_ids=[sel[0]])
    row = _last_row(env)
    assert row["before_ref"] is None and row["after_ref"] is None
    payload = json.loads(row["payload"])
    assert payload["delta"]["added"] == [sel[0]] and payload["delta"]["removed"] == []
    assert "selection" not in payload["_outcome"] and "coverage" not in payload["_outcome"]
    assert set(payload["_outcome"]) == {"dropped", "summary"}
    # 19 KiB per op before (364 ids); the delta row is a few hundred bytes
    assert len(row["payload"]) < 2048, len(row["payload"])


def test_a_replayed_request_returns_its_first_response_after_later_ops(env: Env) -> None:
    sel = env.scope.get().selection
    a, b, c = sel.block_ids[:3]
    other = "structure" if sel.active_view.value == "topic" else "topic"
    _op(env, "deselect", block_ids=[c])
    first = env.scope.apply(SelectionOp(op="deselect", block_ids=[a], request_id="keep"))
    _op(env, "deselect", block_ids=[b])
    _op(env, "select", block_ids=[a])
    _op(env, "set_view", view=other)
    _op(env, "set_split", split="per_document")
    n = env.store.count_actions()
    again = env.scope.apply(SelectionOp(op="deselect", block_ids=[a], request_id="keep"))
    assert again == first
    assert env.store.count_actions() == n  # a replay writes nothing
    assert env.scope.get().selection != first.selection  # the later ops are still applied


def test_the_first_ever_op_replays_too(env: Env) -> None:
    sel = env.scope.get().selection.block_ids
    first = env.scope.apply(SelectionOp(op="deselect", block_ids=sel[:2], request_id="one"))
    _op(env, "select", block_ids=sel[:1])
    assert env.scope.apply(SelectionOp(op="deselect", block_ids=sel[:2], request_id="one")) == (
        first
    )


def test_the_deltas_replayed_forward_rebuild_the_stored_selection(env: Env) -> None:
    sel = env.scope.get().selection
    ids = sel.block_ids
    _op(env, "deselect", block_ids=ids[:5])
    _op(env, "select", block_ids=ids[2:4])
    _op(env, "set_view", view="structure" if sel.active_view.value == "topic" else "topic")
    _op(env, "set_split", split="per_document")
    _op(env, "deselect", block_ids=ids[10:30])
    rebuilt = replay_selection(env.store.iter_actions(), env.store.get_blob)
    stored = env.store.get_selection_json()
    assert stored is not None and rebuilt == Selection.model_validate_json(stored)
    kinds = [a.kind for a in env.store.iter_actions() if a.kind in SELECTION_KINDS]
    assert len(kinds) == 5


def _legacy_row(env: Env, before: Selection, after: Selection, out: SelectionOut, rid: str) -> None:
    """A selection action as the code before F6 wrote it: both snapshots and the full outcome."""
    body = json.dumps(after.model_dump(mode="json"), sort_keys=True)
    with env.store.tx():
        aid = env.store.next_action_id()
        env.store.append_action(
            ActionKind.deselect,
            "scope",
            payload={
                "op": "deselect",
                "block_ids": [],
                "group_id": None,
                "subtree": False,
                "_outcome": out.model_dump(mode="json"),
            },
            before=json.dumps(before.model_dump(mode="json"), sort_keys=True),
            after=body,
            request_id=rid,
            action_id=aid,
        )
        env.store.set_selection_json(body, aid)


def test_rows_written_before_the_change_still_read(env: Env) -> None:
    cur = env.scope.get()
    ids = cur.selection.block_ids
    legacy_after = cur.selection.model_copy(update={"block_ids": ids[1:]})
    legacy_out = cur.model_copy(update={"selection": legacy_after})
    _legacy_row(env, cur.selection, legacy_after, legacy_out, "legacy")
    _op(env, "deselect", block_ids=ids[1:3])
    # a replay of the old request returns its stored outcome verbatim
    again = env.scope.apply(SelectionOp(op="deselect", block_ids=[], request_id="legacy"))
    assert again == legacy_out
    # the forward replay starts from the old row's `after` snapshot and applies the new delta
    rebuilt = replay_selection(env.store.iter_actions(), env.store.get_blob)
    stored = env.store.get_selection_json()
    assert stored is not None and rebuilt == Selection.model_validate_json(stored)
