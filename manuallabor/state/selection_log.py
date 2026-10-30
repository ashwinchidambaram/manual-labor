"""How a selection change is written to the action log, and read back (review F6, design 07
section 16).

A selection action used to carry the selection before and after (two blobs) and the whole
`SelectionOut` (selection, coverage, summary) in its payload: about 68 bytes per selected id per
click. It now carries the change between the stored selection before and after it (`delta`) and
the part of the response that cannot be recomputed (`_outcome`: `dropped` and `summary`).

The log stays replayable both ways, because only these actions write the stored selection
(`ScopeService.apply`; `import_legacy` writes the first one, with an `after` snapshot):

- forward (`replay_selection`): from nothing, each action's `after` snapshot (rows written
  before the change, and `import`) or its delta gives the stored selection after it;
- backward (`selection_at`): from the stored selection, reverting the deltas of the later actions
  gives the selection right after an earlier one, which a replayed request returns.

Rows written before the change keep their snapshots and full `_outcome` and are read as they are;
nothing is migrated."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from manuallabor.contracts.selection import Selection
from manuallabor.state.models import ActionKind, ActionRecord

__all__ = [
    "SELECTION_KINDS",
    "apply_delta",
    "is_legacy_outcome",
    "replay_selection",
    "revert_delta",
    "selection_at",
    "selection_delta",
]

SELECTION_KINDS = (
    ActionKind.select,
    ActionKind.deselect,
    ActionKind.select_group,
    ActionKind.deselect_group,
    ActionKind.set_view,
    ActionKind.set_split,
)

# a selection that was never written, as a delta base: no ids, every other field its default
_EMPTY = Selection(block_ids=[])


def _fields(sel: Selection) -> dict[str, Any]:
    d = sel.model_dump(mode="json")
    d.pop("block_ids")
    return d


def selection_delta(before: Selection | None, after: Selection) -> dict[str, Any]:
    """The change from the stored selection `before` (None: none stored yet) to `after`:
    ids added and removed (in `after`'s order) and every other field that changed, as
    `[old, new]`."""
    base = before if before is not None else _EMPTY
    old_ids = set(base.block_ids)
    new_ids = set(after.block_ids)
    old_f, new_f = _fields(base), _fields(after)
    return {
        "base": "stored" if before is not None else "none",
        "added": [b for b in after.block_ids if b not in old_ids],
        "removed": [b for b in base.block_ids if b not in new_ids],
        "set": {k: [old_f.get(k), v] for k, v in new_f.items() if old_f.get(k) != v},
    }


def apply_delta(before: Selection | None, delta: dict[str, Any]) -> Selection:
    base = _EMPTY if delta.get("base") == "none" or before is None else before
    gone = set(delta.get("removed", ()))
    ids = [b for b in base.block_ids if b not in gone] + list(delta.get("added", ()))
    fields = _fields(base)
    for k, (_old, new) in delta.get("set", {}).items():
        fields[k] = new
    return Selection.model_validate({**fields, "block_ids": ids})


def revert_delta(after: Selection, delta: dict[str, Any]) -> Selection | None:
    """The stored selection before the action (None when there was none)."""
    if delta.get("base") == "none":
        return None
    added = set(delta.get("added", ()))
    ids = [b for b in after.block_ids if b not in added] + list(delta.get("removed", ()))
    fields = _fields(after)
    for k, (old, _new) in delta.get("set", {}).items():
        fields[k] = old
    return Selection.model_validate({**fields, "block_ids": ids})


def is_legacy_outcome(payload: dict[str, Any]) -> bool:
    """A row written before F6: its `_outcome` is the whole `SelectionOut`."""
    out = payload.get("_outcome")
    return isinstance(out, dict) and "selection" in out


def _snapshot(body: str | None) -> Selection | None:
    return None if body is None else Selection.model_validate_json(body)


def replay_selection(
    actions: Iterable[ActionRecord], get_blob: Callable[[str | None], str | None]
) -> Selection | None:
    """The stored selection rebuilt from the action log alone (forward replay)."""
    sel: Selection | None = None
    for a in actions:
        if a.kind == ActionKind.import_ and a.payload.get("what") == "selection":
            sel = _snapshot(get_blob(a.after_ref))
        elif a.kind in SELECTION_KINDS:
            delta = a.payload.get("delta")
            if isinstance(delta, dict):
                sel = apply_delta(sel, delta)
            elif a.after_ref is not None:
                sel = _snapshot(get_blob(a.after_ref))
    return sel


def selection_at(current: Selection | None, later: Sequence[ActionRecord]) -> Selection | None:
    """The stored selection right after an action, from the stored selection now (`current`)
    and every selection action written after it (`later`, oldest first), reverting their deltas
    newest first. Raises ValueError on a later row without a delta (written before F6; it can
    only be older than every row with one, so a caller never needs to cross it)."""
    sel = current
    for a in reversed(later):
        delta = a.payload.get("delta")
        if not isinstance(delta, dict):
            raise ValueError(f"action {a.id} has no selection delta")
        if sel is None:
            raise ValueError(f"no stored selection after action {a.id}")
        sel = revert_delta(sel, delta)
    return sel
