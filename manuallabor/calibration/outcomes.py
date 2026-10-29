"""Outcomes: what the reviewers did with each (block, raw text) the machine scored (design 10
section 4.1). The single source for the buckets, the signal statistics, the learning derivers
and the A/B replay. Pure over action rows."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from manuallabor.calibration.types import Outcome
from manuallabor.state.models import ActionKind, ActionRecord

__all__ = ["doc_kind_of", "outcome_of", "outcomes"]

_EDIT_KINDS = frozenset({ActionKind.edit, ActionKind.proposal_accept, ActionKind.proposal_edit})
_WRONG_FLAGS = frozenset({"wrong_text", "table_structure", "bad_crop"})
_TEXT_PROPOSALS = frozenset({"text", "cells"})


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_kind_of(raw_source: str | None) -> str:
    if raw_source in ("ocr", "ocr_alt"):
        return "scanned_pdf"
    if raw_source == "docx":
        return "docx"
    return "born_digital_pdf"


def outcome_of(a: ActionRecord) -> Outcome | None:
    """The outcome one action records, or None when it is not one (design 10 section 4.1)."""
    ex = a.example
    if not isinstance(ex, dict):
        return None
    if a.kind not in _EDIT_KINDS and a.kind not in (ActionKind.approve, ActionKind.flag):
        return None
    score = ex.get("score")
    block_id = ex.get("block_id")
    raw = ex.get("raw_text")
    if not isinstance(block_id, str) or score is None or not isinstance(raw, str):
        return None
    raw_sha = str(ex.get("raw_sha256") or _sha(raw))
    shown = ex.get("clean_before")
    shown_text = shown if isinstance(shown, str) else raw
    final = ex.get("clean_after")
    edited: bool
    final_text: str | None = None
    if a.kind == ActionKind.approve:
        edited = False
        final_text = shown_text
    elif a.kind in _EDIT_KINDS:
        if a.kind == ActionKind.proposal_accept:
            prop = ex.get("proposal")
            if not isinstance(prop, dict) or prop.get("kind") not in _TEXT_PROPOSALS:
                return None
        if not isinstance(final, str):
            return None
        final_text = final
        edited = _sha(final) != _sha(shown_text)
    else:  # flag
        if ex.get("flag_category") not in _WRONG_FLAGS:
            return None
        edited = True
    sigs: list[tuple[str, float, bool]] = []
    for s in ex.get("signals") or []:
        if isinstance(s, dict) and "name" in s and "value" in s:
            sigs.append((str(s["name"]), float(s["value"]), bool(s.get("critical", False))))
    source = "agent" if a.kind == ActionKind.proposal_accept else "human"
    prov = a.learning_provenance or str(ex.get("learning_provenance") or "baseline")
    return Outcome(
        block_id=block_id,
        raw_sha=raw_sha,
        action_id=a.id,
        score=float(score),
        numeric=bool(ex.get("has_numeric_spec", False)),
        block_type=str(ex.get("block_type", "paragraph")),
        doc_kind=doc_kind_of(ex.get("raw_source")),
        edited=edited,
        source=source,
        provenance=prov,
        signals=tuple(sorted(sigs)),
        shown_sha=_sha(shown_text),
        final_sha=None if final_text is None else _sha(final_text),
        final_text=final_text,
        shown_text=shown_text,
    )


def outcomes(actions: Iterable[ActionRecord]) -> list[Outcome]:
    """One outcome per (block, raw text): the latest relevant action by id. A re-parse that
    changes the raw text keeps the earlier observation (the score was real for that text)."""
    latest: dict[tuple[str, str], Outcome] = {}
    for a in sorted(actions, key=lambda x: x.id):
        o = outcome_of(a)
        if o is not None:
            latest[(o.block_id, o.raw_sha)] = o
    return sorted(latest.values(), key=lambda o: o.action_id)
