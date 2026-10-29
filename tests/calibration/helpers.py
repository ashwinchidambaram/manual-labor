"""Synthetic decisions: action rows with the example payload the review service records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from manuallabor.state.models import ActionKind, ActionRecord
from manuallabor.state.store import Store

TS = datetime(2026, 1, 1, tzinfo=UTC)


def example(
    block_id: str,
    raw: str,
    *,
    score: float | None = 0.9,
    shown: str | None = None,
    final: str | None = None,
    numeric: bool = False,
    block_type: str = "paragraph",
    raw_source: str = "pymupdf",
    signals: list[dict[str, Any]] | None = None,
    faith: bool | None = True,
    flag_category: str | None = None,
    flag_note: str | None = None,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "doc_id": "clean",
        "block_type": block_type,
        "raw_text": raw,
        "raw_source": raw_source,
        "raw_text_by_parser": {raw_source: raw},
        "clean_before": shown,
        "clean_after": final if final is not None else (shown if shown is not None else raw),
        "signals": signals or [],
        "score": score,
        "threshold": 0.85,
        "has_numeric_spec": numeric,
        "action": "edit",
        "flag_category": flag_category,
        "flag_note": flag_note,
        "faith_passed": faith,
        "learning_provenance": "baseline",
        "proposal": proposal,
    }


def record(
    i: int, kind: ActionKind, ex: dict[str, Any] | None, *, prov: str | None = None
) -> ActionRecord:
    return ActionRecord(
        id=i, ts=TS, screen="verify", kind=kind, example=ex, learning_provenance=prov
    )


def add(store: Store, kind: ActionKind, ex: dict[str, Any], screen: str = "verify") -> int:
    with store.tx():
        return store.append_action(
            kind, screen, target_id=ex["block_id"], doc_id="clean", example=ex
        )
