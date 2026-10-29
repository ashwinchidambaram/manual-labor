"""The learned-vs-baseline guardrail (design 10 section 5.4). Deterministic cleanup replay on
the decisions the active snapshot never learned from; the LLM is not replayed. The observed
edit rates per provenance are shown beside it, labelled as not a controlled comparison."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from manuallabor.calibration.buckets import wilson
from manuallabor.calibration.types import (
    AB_MIN_DISCORDANT,
    AB_MIN_N,
    DiscordantPairs,
    LearnedQueue,
    Outcome,
    ProvenanceRate,
)
from manuallabor.contracts._base import round6
from manuallabor.contracts.io import read_json_list
from manuallabor.parse.text import collapse_ws
from manuallabor.project import ProjectPaths
from manuallabor.state.models import CalibrationAB

__all__ = ["AbRow", "ab_core", "ab_replay", "observed_by_provenance"]


@dataclass(frozen=True)
class AbRow:
    final: str  # the text the human accepted or wrote
    out_base: str  # deterministic cleanup without the learned layer
    out_learn: str  # with it
    edited: bool
    added: bool  # the learned scoring items newly queue this (otherwise auto-approved) block


def ab_core(rows: Sequence[AbRow], *, snapshot: str, holdout: bool) -> CalibrationAB:
    """Pure: the rates, the discordant pairs and the verdict of the replay."""
    n = len(rows)
    need_b = [collapse_ws(r.out_base) != collapse_ws(r.final) for r in rows]
    need_l = [collapse_ws(r.out_learn) != collapse_ws(r.final) for r in rows]
    b = sum(1 for x, y in zip(need_b, need_l, strict=True) if not x and y)
    c = sum(1 for x, y in zip(need_b, need_l, strict=True) if x and not y)
    verdict = "no_difference"
    if c - b >= AB_MIN_DISCORDANT and c > 2 * b:
        verdict = "learned_better"
    elif b - c >= AB_MIN_DISCORDANT and b > 2 * c:
        verdict = "learned_worse"
    if not holdout or n < AB_MIN_N:
        verdict = "insufficient"
    added = [r for r in rows if r.added]
    return CalibrationAB(
        baseline_n=n,
        baseline_edit_rate=None if n == 0 else round6(sum(need_b) / n),
        learned_n=n,
        learned_edit_rate=None if n == 0 else round6(sum(need_l) / n),
        verdict=verdict,  # type: ignore[arg-type]
        method="holdout" if holdout and n >= AB_MIN_N else "in_sample",
        snapshot=snapshot,
        discordant=DiscordantPairs(b=b, c=c),
        learned_queue=LearnedQueue(
            added=len(added), edited_among_added=sum(r.edited for r in added)
        ),
    )


def observed_by_provenance(outs: Sequence[Outcome]) -> list[ProvenanceRate]:
    """Edit rate of reviewed decisions per learning provenance. Not a controlled comparison."""
    n: dict[str, int] = defaultdict(int)
    e: dict[str, int] = defaultdict(int)
    for o in outs:
        n[o.provenance] += 1
        e[o.provenance] += int(o.edited)
    rows = []
    for p in sorted(n):
        lo, hi = wilson(e[p], n[p])
        rows.append(
            ProvenanceRate(
                provenance=p,
                n=n[p],
                edited=e[p],
                edit_rate=round6(e[p] / n[p]),
                wilson_lo=lo,
                wilson_hi=hi,
            )
        )
    return rows


def ab_replay(
    paths: ProjectPaths,
    data: object,
    snapshot_id: str,
    last_action: int | None,
    outs: Sequence[Outcome],
) -> CalibrationAB:
    """The replay of the snapshot on the project's own decisions (I/O around `ab_core`)."""
    from manuallabor.calibration.types import LearnedCalibration
    from manuallabor.cleanup.pipeline import clean_document, cleanable
    from manuallabor.cleanup.types import LearnedCleanup
    from manuallabor.contracts.enums import BlockStatus
    from manuallabor.parse.types import PageLayout
    from manuallabor.scoring.learned import learned_confusables, lexicon_specs
    from manuallabor.state.data import ProjectData

    assert isinstance(data, ProjectData)
    sdir = paths.snapshot_dir(snapshot_id)
    cf = sdir / "cleanup.json"
    learned = (
        LearnedCleanup.model_validate_json(cf.read_text(encoding="utf-8")) if cf.is_file() else None
    )
    lcal = None
    if (sdir / "calibration.json").is_file():
        lcal = LearnedCalibration.model_validate_json(
            (sdir / "calibration.json").read_text(encoding="utf-8")
        )
    human = [o for o in outs if o.source == "human" and o.final_text is not None]
    cur_raw: dict[str, str] = {}
    blocks_by_doc: dict[str, dict[str, object]] = {}
    from manuallabor import ids
    from manuallabor.state.store import sha_text

    pool: list[tuple[Outcome, str]] = []
    for o in human:
        slug = ids.parse_block_id(o.block_id)[0]
        if slug not in paths.list_slugs():
            continue
        blocks = {b.id: b for b in data.raw_blocks(slug)}
        blk = blocks.get(o.block_id)
        if blk is None or sha_text(blk.raw_text) != o.raw_sha or not cleanable(blk):
            continue
        pool.append((o, slug))
        blocks_by_doc[slug] = blocks  # type: ignore[assignment]
    holdout_set = [(o, s) for o, s in pool if last_action is not None and o.action_id > last_action]
    holdout = len(holdout_set) >= AB_MIN_N
    chosen = holdout_set if holdout else pool
    rows: list[AbRow] = []
    by_doc: dict[str, list[Outcome]] = defaultdict(list)
    for o, s in chosen:
        by_doc[s].append(o)
    for slug in sorted(by_doc):
        doc = data.document(slug)
        raw_blocks = data.raw_blocks(slug)
        dp = paths.doc(slug)
        layouts = read_json_list(dp.layout, PageLayout) if dp.layout.is_file() else []
        sel = {o.block_id for o in by_doc[slug]}
        base, _ = clean_document(doc, raw_blocks, layouts, sel, mode="off", learned=None)
        lrn, _ = clean_document(doc, raw_blocks, layouts, sel, mode="off", learned=learned)
        tb = {e.block_id: e.clean_text for e in base}
        tl = {e.block_id: e.clean_text for e in lrn}
        machine = {b.id: b for b in data.machine_blocks(slug)}
        lex = tuple(lcal.lexicon) if lcal is not None else ()
        conf = tuple(lcal.confusions) if lcal is not None else ()
        for o in by_doc[slug]:
            m = machine.get(o.block_id)
            added = False
            if m is not None and m.status == BlockStatus.auto_approved:
                texts = [m.raw_text, *m.raw_text_by_parser.values()]
                added = any(lexicon_specs(t, lex) for t in texts) or bool(
                    learned_confusables(m.raw_text, conf)
                )
            assert o.final_text is not None
            rows.append(AbRow(o.final_text, tb[o.block_id], tl[o.block_id], o.edited, added))
    del cur_raw, blocks_by_doc
    return ab_core(rows, snapshot=snapshot_id, holdout=holdout)
