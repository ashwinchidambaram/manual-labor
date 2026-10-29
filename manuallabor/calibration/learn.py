"""Derivers of the learning snapshot files and their miners (design 10 section 5.1).

Every function is pure over action rows: the same rows give the same bytes. Mined items can only
make the machine more careful (queue more, lower confidence) or change proposals; nothing here
loosens a faithfulness check, raises a confidence or lowers the threshold."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from manuallabor.calibration.outcomes import outcomes
from manuallabor.calibration.signals import promotions, signal_reliability
from manuallabor.calibration.suggest import suggest_threshold
from manuallabor.calibration.types import (
    CONFUSION_MIN_SUPPORT,
    LEXICON_MIN_SUPPORT,
    RULE_MIN_SUPPORT,
    AgentExample,
    ConfusionPair,
    LearnedAgent,
    LearnedCalibration,
    LexiconEntry,
    Outcome,
)
from manuallabor.cleanup.rules import DH_RE
from manuallabor.cleanup.types import LearnedCleanup, LearnedRule
from manuallabor.contracts.enums import BlockType
from manuallabor.scoring.faithfulness import BULLETS, ocr_confusable
from manuallabor.scoring.numeric import NUM, find_numeric_specs
from manuallabor.state.learning import derive_cleanup
from manuallabor.state.models import ActionKind, ActionRecord

__all__ = [
    "derive_agent",
    "derive_calibration",
    "derive_cleanup_v2",
    "mine_bullet_rules",
    "mine_confusions",
    "mine_hyphen_rules",
    "mine_lexicon",
]

DEFAULT_TARGET = 0.02
AGENT_EXAMPLES_MAX = 100


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def _final_edits(actions: list[ActionRecord]) -> list[ActionRecord]:
    """Latest edit/accept per block whose final text passed the strict faithfulness check."""
    latest: dict[str, ActionRecord] = {}
    for a in actions:
        if a.kind in (ActionKind.edit, ActionKind.proposal_accept, ActionKind.proposal_edit) and (
            a.example is not None
        ):
            latest[str(a.example.get("block_id"))] = a
    return [a for _id, a in sorted(latest.items()) if (a.example or {}).get("faith_passed") is True]


def mine_hyphen_rules(actions: list[ActionRecord]) -> list[LearnedRule]:
    keep: dict[str, set[str]] = defaultdict(set)
    drop: dict[str, set[str]] = defaultdict(set)
    types: dict[str, set[BlockType]] = defaultdict(set)
    for a in _final_edits(actions):
        ex = a.example or {}
        raw, machine, final = ex.get("raw_text"), ex.get("clean_before"), ex.get("clean_after")
        if not (isinstance(raw, str) and isinstance(final, str)):
            continue
        machine = machine if isinstance(machine, str) else raw
        try:
            btype = BlockType(str(ex.get("block_type")))
        except ValueError:
            continue
        for m in DH_RE.finditer(raw):
            left, right = m.group("L"), m.group("R")
            value = f"{left}-{right}".casefold()
            joined = re.compile(rf"\b{re.escape(left + right)}\b", re.I)
            hyph = re.compile(rf"\b{re.escape(left)}-{re.escape(right)}\b", re.I)
            if joined.search(machine) and hyph.search(final) and not hyph.search(machine):
                keep[value].add(str(ex["block_id"]))
                types[value].add(btype)
            elif hyph.search(machine) and joined.search(final) and not joined.search(machine):
                drop[value].add(str(ex["block_id"]))
                types[value].add(btype)
    out: list[LearnedRule] = []
    for value in sorted(set(keep) | set(drop)):
        k, d = keep.get(value, set()), drop.get(value, set())
        if k and d:
            continue
        votes = k or d
        if len(votes) < RULE_MIN_SUPPORT:
            continue
        out.append(
            LearnedRule(
                id=f"rule-h-{_sha8(value)}",
                kind="hyphen_keep" if k else "hyphen_drop",
                value=value,
                block_types=sorted(types[value], key=lambda t: t.value),
                support=len(votes),
            )
        )
    return out


def mine_bullet_rules(actions: list[ActionRecord]) -> list[LearnedRule]:
    votes: dict[tuple[str, BlockType], set[str]] = defaultdict(set)
    for a in _final_edits(actions):
        ex = a.example or {}
        raw, machine, final = ex.get("raw_text"), ex.get("clean_before"), ex.get("clean_after")
        try:
            btype = BlockType(str(ex.get("block_type")))
        except ValueError:
            continue
        if btype == BlockType.list or not (isinstance(raw, str) and isinstance(final, str)):
            continue
        machine = machine if isinstance(machine, str) else raw
        mlines, flines = machine.split("\n"), final.split("\n")
        for ln in raw.split("\n"):
            if len(ln) < 3 or ln[0] not in BULLETS or ln[1] != " ":
                continue
            g, rest = ln[0], ln[2:]
            if f"{g} {rest}" in mlines and f"• {rest}" in flines:
                votes[(g, btype)].add(str(ex["block_id"]))
    out: list[LearnedRule] = []
    for (g, btype), blocks in sorted(votes.items(), key=lambda kv: (kv[0][0], kv[0][1].value)):
        if len(blocks) >= RULE_MIN_SUPPORT:
            out.append(
                LearnedRule(
                    id=f"rule-b-{_sha8(g + btype.value)}",
                    kind="bullet_glyph",
                    value=g,
                    block_types=[btype],
                    support=len(blocks),
                )
            )
    return out


def derive_cleanup_v2(
    actions: list[ActionRecord], seq_of_action: dict[int, int], snap: str
) -> LearnedCleanup:
    v1 = derive_cleanup(actions, seq_of_action, snap)
    rules = sorted([*mine_hyphen_rules(actions), *mine_bullet_rules(actions)], key=lambda r: r.id)
    return LearnedCleanup(snapshot=snap, rules=rules, examples=v1.examples)


def mine_confusions(outs: list[Outcome]) -> list[ConfusionPair]:
    """(wrong, right) character pairs where the only change a reviewer made to a token is an
    OCR look-alike (`scoring.faithfulness.ocr_confusable` on the whole token: same length,
    every differing pair inside one confusable group), with a digit on at least one side of
    the pair and in the corrected token."""
    blocks: dict[tuple[str, str], set[str]] = defaultdict(set)
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for o in outs:
        if not o.edited or o.final_text is None or o.shown_text is None:
            continue
        a, b = o.shown_text.split(), o.final_text.split()
        pairs: list[tuple[str, str, str]] = []
        ok = True
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            if tag != "replace" or (i2 - i1) != (j2 - j1):
                ok = False
                break
            for w_tok, r_tok in zip(a[i1:i2], b[j1:j2], strict=True):
                # the whole token change must be a look-alike (same length, every differing
                # pair inside one confusable group): `35`->`45` is a new value, not a misread
                if not ocr_confusable(w_tok, r_tok) or not any(c.isdigit() for c in r_tok):
                    ok = False
                    break
                for w, r in zip(w_tok, r_tok, strict=True):
                    if w != r:
                        if not (w.isdigit() or r.isdigit()):
                            ok = False
                            break
                        pairs.append((w, r, f"{w_tok}→{r_tok}"))
                if not ok:
                    break
            if not ok:
                break
        if ok:
            for w, r, ex in pairs:
                blocks[(w, r)].add(o.block_id)
                if ex not in examples[(w, r)] and len(examples[(w, r)]) < 3:
                    examples[(w, r)].append(ex)
    out: list[ConfusionPair] = []
    for (w, r), bs in sorted(blocks.items()):
        s = len(bs)
        if s < CONFUSION_MIN_SUPPORT:
            continue
        if len(blocks.get((r, w), ())) * 2 >= s:
            continue
        out.append(
            ConfusionPair(
                id=f"conf-{ord(w):04x}-{ord(r):04x}",
                wrong=w,
                right=r,
                support=s,
                examples=sorted(examples[(w, r)]),
            )
        )
    return out


_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"|“([^”]+)”|‘([^’]+)’")
_NUMUNIT = re.compile(rf"{NUM}\s?[A-Za-z°µΩ][\w°µΩ./·-]{{0,9}}")
_KEYWORD = re.compile(r"^([A-Za-z]{2,6})[-\s.:#]?\d")
_UNIT = re.compile(r"^[A-Za-z°µΩ][\w°µΩ./·-]{0,9}$")


def mine_lexicon(actions: list[ActionRecord]) -> list[LexiconEntry]:
    """Units and part-number keywords the reviewers pointed at in `wrong_text` flag notes on
    blocks that were not numeric specs, kept only when they occur verbatim in the raw text."""
    support: dict[tuple[str, str], set[str]] = defaultdict(set)
    for a in actions:
        ex = a.example
        if a.kind != ActionKind.flag or not isinstance(ex, dict):
            continue
        note, raw = ex.get("flag_note"), ex.get("raw_text")
        if (
            ex.get("flag_category") != "wrong_text"
            or ex.get("has_numeric_spec")
            or not isinstance(note, str)
            or not isinstance(raw, str)
        ):
            continue
        cands = [next(g for g in m.groups() if g) for m in _QUOTED.finditer(note)]
        cands += [m.group(0) for m in _NUMUNIT.finditer(note)]
        for c in cands:
            c = c.strip()
            if not c or c not in raw or find_numeric_specs(c, None):
                continue
            bid = str(ex.get("block_id"))
            m = re.match(rf"^{NUM}\s?(?P<u>[A-Za-z°µΩ][\w°µΩ./·-]{{0,9}})$", c)
            if m is not None:
                support[("unit", m.group("u"))].add(bid)
            elif _UNIT.match(c) and re.search(rf"{NUM}\s?{re.escape(c)}(?![A-Za-z])", raw):
                support[("unit", c)].add(bid)
            else:
                k = _KEYWORD.match(c)
                if k is not None:
                    support[("part_keyword", k.group(1))].add(bid)
    out: list[LexiconEntry] = []
    for (kind, value), bs in sorted(support.items()):
        if len(bs) >= LEXICON_MIN_SUPPORT:
            out.append(
                LexiconEntry(
                    id=f"lex-{kind[:1]}-{_sha8(value)}",
                    kind=kind,  # type: ignore[arg-type]
                    value=value,
                    support=len(bs),
                )
            )
    return out


def derive_calibration(
    actions: list[ActionRecord], seq_of_action: dict[int, int], snap: str
) -> LearnedCalibration:
    outs = outcomes(actions)
    sug, _w = suggest_threshold(outs, DEFAULT_TARGET, None)
    rel = signal_reliability(outs, DEFAULT_TARGET)
    return LearnedCalibration(
        snapshot=snap,
        threshold=sug,
        signal_reliability=rel,
        critical_promotions=promotions(rel),
        confusions=mine_confusions(outs),
        lexicon=mine_lexicon(actions),
    )


def derive_agent(
    actions: list[ActionRecord], seq_of_action: dict[int, int], snap: str
) -> LearnedAgent:
    rows: list[AgentExample] = []
    for a in actions:
        ex: Any = a.example
        if not isinstance(ex, dict) or not isinstance(ex.get("proposal"), dict):
            continue
        prop = ex["proposal"]
        if prop.get("kind") not in ("text", "cells"):
            continue
        cat = "wrong_text" if prop["kind"] == "text" else "table_structure"
        if a.kind == ActionKind.proposal_accept:
            shown = ex.get("clean_before")
            rows.append(
                AgentExample(
                    id=f"agex-{a.id}",
                    category=cat,
                    block_type=str(ex.get("block_type", "paragraph")),
                    before=shown if isinstance(shown, str) else str(ex.get("raw_text", "")),
                    after=prop.get("proposal_text"),
                    outcome="accepted",
                )
            )
        elif a.kind == ActionKind.proposal_edit and ex.get("faith_passed") is True:
            shown = ex.get("clean_before")
            rows.append(
                AgentExample(
                    id=f"agex-{a.id}",
                    category=cat,
                    block_type=str(ex.get("block_type", "paragraph")),
                    before=shown if isinstance(shown, str) else str(ex.get("raw_text", "")),
                    after=ex.get("clean_after"),
                    outcome="edited",
                )
            )
        elif a.kind == ActionKind.proposal_reject:
            rows.append(
                AgentExample(
                    id=f"agex-{a.id}",
                    category=cat,
                    block_type=str(ex.get("block_type", "paragraph")),
                    before=str(ex.get("before", "")),
                    after=prop.get("proposal_text"),
                    outcome="rejected",
                    reason=ex.get("reason"),
                )
            )
    return LearnedAgent(snapshot=snap, examples=rows[-AGENT_EXAMPLES_MAX:])
