"""The learned scoring layer (design 10 section 5.2, scoring M3b): lexicon, OCR confusions and
critical promotions read from the materialized `learning/calibration.json`.

Every effect is one-directional: more blocks are queued (lexicon, confusions) or confidence can
only go down (promotions). Nothing here raises a confidence, lowers the threshold or loosens a
check; with `learning.enabled` off, or no snapshot, this module returns None and scoring is the
baseline byte for byte."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from pydantic import ValidationError

from manuallabor.calibration.types import (
    LEXICON_MAX_DOC_FRAC,
    ConfusionPair,
    CriticalPromotion,
    LearnedCalibration,
    LexiconEntry,
)
from manuallabor.contracts.block import Block, Signal
from manuallabor.contracts.config import ProjectConfig
from manuallabor.parse.text import TOKEN_RE
from manuallabor.project import ProjectPaths
from manuallabor.scoring.numeric import NUM

log = logging.getLogger(__name__)

BASELINE: Final = "baseline"


@dataclass(frozen=True)
class LearnedScoring:
    snapshot: str
    sha: str
    confusions: tuple[ConfusionPair, ...] = ()
    lexicon: tuple[LexiconEntry, ...] = ()
    promotions: tuple[CriticalPromotion, ...] = ()
    ignored: tuple[str, ...] = field(default=(), compare=False)


def load_learned_scoring(paths: ProjectPaths, config: ProjectConfig) -> LearnedScoring | None:
    """The active snapshot's calibration layer, or None (learning off, none active, unreadable)."""
    if not config.learning.enabled:
        return None
    p = paths.learned_calibration
    if not p.is_file():
        return None
    data = p.read_bytes()
    try:
        lc = LearnedCalibration.model_validate_json(data)
    except (ValidationError, ValueError) as exc:
        log.warning("learned calibration %s is unreadable, using baseline: %s", p, exc)
        return None
    # a one-char wrong glyph is the only confusion shape the scorer can apply
    conf = tuple(c for c in lc.confusions if len(c.wrong) == 1 and len(c.right) == 1)
    return LearnedScoring(
        snapshot=lc.snapshot,
        sha=hashlib.sha256(data).hexdigest(),
        confusions=tuple(sorted(conf, key=lambda c: c.id)),
        lexicon=tuple(sorted(lc.lexicon, key=lambda e: e.id)),
        promotions=tuple(sorted(lc.critical_promotions, key=lambda x: x.id)),
    )


@lru_cache(maxsize=256)
def _unit_rx(unit: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.]){NUM}\s?{re.escape(unit)}(?![A-Za-z])")


@lru_cache(maxsize=256)
def _kw_rx(kw: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(kw)}[-\s.:#]*[A-Z0-9][A-Z0-9./-]{{2,}}")


def lexicon_specs(text: str, entries: Iterable[LexiconEntry]) -> list[str]:
    """Spec strings the learned lexicon finds in text (text order, de-duplicated)."""
    hits: list[tuple[int, str]] = []
    for e in entries:
        rx = _unit_rx(e.value) if e.kind == "unit" else _kw_rx(e.value)
        for m in rx.finditer(text):
            s = m.group(0).strip()
            if e.kind == "part_keyword" and not any(ch.isdigit() for ch in s):
                continue
            hits.append((m.start(), s))
    hits.sort()
    return list(dict.fromkeys(s for _, s in hits))


def block_texts(b: Block) -> list[str]:
    return [b.raw_text, *(b.raw_text_by_parser[k] for k in sorted(b.raw_text_by_parser))]


def active_lexicon(
    learned: LearnedScoring | None, blocks: Sequence[Block]
) -> tuple[tuple[LexiconEntry, ...], list[str]]:
    """The lexicon entries to use for one document: an entry that matches more than
    LEXICON_MAX_DOC_FRAC of the document's text blocks is ignored (and reported)."""
    if learned is None or not learned.lexicon:
        return (), []
    body = [
        b
        for b in blocks
        if b.raw_text.strip() and b.type.value not in ("figure", "header", "footer")
    ]
    keep: list[LexiconEntry] = []
    ignored: list[str] = []
    for e in learned.lexicon:
        hit = sum(1 for b in body if lexicon_specs(b.raw_text, (e,)))
        if body and hit / len(body) > LEXICON_MAX_DOC_FRAC:
            ignored.append(e.id)
            log.warning(
                "learned lexicon entry %s ignored: matches %d/%d blocks", e.id, hit, len(body)
            )
        else:
            keep.append(e)
    return tuple(keep), ignored


def learned_confusables(text: str, confusions: Iterable[ConfusionPair]) -> list[str]:
    """why-items for tokens that hold a digit next to a learned wrong glyph (`3S`, `S5`)."""
    out: list[str] = []
    conf = list(confusions)
    if not conf:
        return out
    for m in TOKEN_RE.finditer(text):
        tok = m.group()
        if not any(ch.isdigit() for ch in tok):
            continue
        for c in conf:
            w = c.wrong
            for i, ch in enumerate(tok):
                if ch != w:
                    continue
                prev_d = i > 0 and tok[i - 1].isdigit()
                next_d = i + 1 < len(tok) and tok[i + 1].isdigit()
                if prev_d or next_d:
                    why = f"learned: {w!r} for {c.right!r}"
                    if why not in out:
                        out.append(why)
                    break
    return out


def promote(signals: Sequence[Signal], promotions: Iterable[CriticalPromotion]) -> list[Signal]:
    """The signals with every promoted one made critical (value unchanged)."""
    below = {p.signal: p.below for p in promotions}
    out: list[Signal] = []
    for s in signals:
        cut = below.get(s.name.value)
        if cut is not None and not s.critical and s.value < cut:
            out.append(s.model_copy(update={"critical": True}))
        else:
            out.append(s)
    return out


def dump(lc: LearnedCalibration) -> str:
    return json.dumps(lc.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
