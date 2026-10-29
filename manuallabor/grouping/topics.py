"""Topic view: cluster, name, place stragglers, bind captions and headings, apply overrides
(design §3). One topic set per document."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import (
    BlockType,
    GroupView,
    Task,
    TitleSource,
    UnassignedReason,
)
from manuallabor.contracts.group import (
    Group,
    GroupingParams,
    GroupOverride,
    StragglerRecord,
    UnassignedEntry,
)
from manuallabor.grouping.cluster import center, centroid, cluster, cohesion
from manuallabor.grouping.embed import embed_blocks
from manuallabor.grouping.label import (
    StragglerItem,
    name_topic,
    rank_headings,
    review_stragglers,
)
from manuallabor.grouping.learning import LearnedGrouping, pick_examples
from manuallabor.grouping.overrides import apply_overrides
from manuallabor.grouping.structure import is_header_footer, page_ranges
from manuallabor.grouping.summary import block_summaries, bound_captions, is_no_text
from manuallabor.grouping.types import (
    MAX_EXAMPLES,
    MIN_FINAL_TOPIC_BLOCKS,
    UNASSIGNED_TITLE,
    Assembly,
    GroupingError,
    GroupStats,
    StragglerDecision,
    StructureResult,
    TopicFailure,
)
from manuallabor.providers.base import Provider, ProviderError, ProviderSet


@dataclass
class TopicResult:
    topics: list[Group]  # t000 first
    unassigned: list[UnassignedEntry]  # topic-view entries: header/footer and t000 members
    stragglers: list[StragglerRecord]
    title_sources: dict[str, TitleSource]
    status: Literal["ok", "failed"]
    error: str | None
    embedding_dim: int
    overrides_applied: int
    overrides_stale: list[int]
    stats: GroupStats = field(default_factory=GroupStats)


def _provider(providers: ProviderSet, task: Task) -> Provider:
    try:
        return providers.get(task)
    except ProviderError as exc:
        raise GroupingError(f"no provider for {task}: {exc}") from exc


def _place_stragglers(
    c: np.ndarray,
    cand_ids: Sequence[str],
    summaries: Mapping[str, str],
    in_cluster: set[int],
    centroids: np.ndarray,
    keys: Sequence[str],
    titles: Mapping[str, str],
    chat: Provider,
    params: GroupingParams,
    examples: Sequence[Mapping[str, str]],
    stats: GroupStats,
) -> list[StragglerDecision]:
    rows = [r for r in range(len(cand_ids)) if r not in in_cluster]
    if not rows:
        return []
    sims = np.round(c[rows] @ centroids.T, 9)
    defaults: dict[str, StragglerDecision] = {}
    cands: dict[str, list[tuple[str, float]]] = {}
    for i, r in enumerate(rows):
        bid = cand_ids[r]
        ranked = sorted(range(len(keys)), key=lambda k: (-float(sims[i, k]), keys[k]))
        best = float(sims[i, ranked[0]])
        top = [
            (keys[k], float(sims[i, k]))
            for k in ranked[: params.n_candidates]
            if float(sims[i, k]) >= params.t_candidate
        ]
        cands[bid] = top
        if top and top[0][1] >= params.t_assign:
            defaults[bid] = StragglerDecision(bid, top[0][0], top[0][1], "centroid")
        else:
            defaults[bid] = StragglerDecision(bid, None, best, "centroid")
    out = dict(defaults)
    if params.llm_stragglers:
        reviewable = [
            StragglerItem(
                cand_ids[r], summaries[cand_ids[r]], tuple(k for k, _ in cands[cand_ids[r]])
            )
            for r in rows
            if cands[cand_ids[r]]
        ]
        topic_list = [(k, titles[k]) for k in keys]
        for i in range(0, len(reviewable), params.straggler_batch):
            batch = reviewable[i : i + params.straggler_batch]
            res = review_stragglers(chat, topic_list, batch, examples=examples)
            if res is None:
                stats.straggler_fallbacks += 1
                continue
            for it in batch:
                chosen = res[it.block_id]
                best = max(s for _, s in cands[it.block_id])
                if chosen == "unassigned":
                    out[it.block_id] = StragglerDecision(it.block_id, None, best, "llm")
                else:
                    sim = dict(cands[it.block_id])[chosen]
                    out[it.block_id] = StragglerDecision(it.block_id, chosen, sim, "llm")
    return [out[cand_ids[r]] for r in rows]


def _bind(
    asm: Assembly,
    captions: Mapping[str, str],
    structure: StructureResult,
) -> None:
    """§3.6 steps 2-3: a caption follows its figure, a heading follows its section."""
    for fig, cap in sorted(captions.items(), key=lambda kv: ids.block_sort_key(kv[0])):
        if asm.reasons.get(cap) == UnassignedReason.no_text and asm.placed.get(cap) is None:
            continue
        key = asm.placed.get(fig)
        asm.placed[cap] = key
        if key is None:
            asm.reasons[cap] = asm.reasons.get(fig, UnassignedReason.low_similarity)
        else:
            asm.reasons.pop(cap, None)
    for g in structure.groups:
        head = structure.heading_of.get(g.id)
        if head is None:
            continue
        counts: Counter[str] = Counter()
        first: dict[str, int] = {}
        for b in g.block_ids:
            if b == head or b not in asm.placed:
                continue
            k = asm.placed[b]
            if k is None:
                continue
            counts[k] += 1
            first.setdefault(k, len(first))
        if not counts:
            continue
        best = sorted(counts, key=lambda k: (-counts[k], first[k]))[0]
        asm.placed[head] = best
        asm.reasons.pop(head, None)


def _dissolve_small(asm: Assembly) -> None:
    for key, members in asm.members().items():
        if len(members) < MIN_FINAL_TOPIC_BLOCKS:
            for b in members:
                asm.placed[b] = None
                asm.reasons[b] = UnassignedReason.low_similarity
            for d in (asm.titles, asm.slugs, asm.sources):
                d.pop(key, None)


def _page_figures(blocks: Sequence[Block]) -> tuple[list[int], int]:
    return [b.page for b in blocks], sum(1 for b in blocks if b.type == BlockType.figure)


def build_topics(
    doc: Document,
    blocks: Sequence[Block],
    structure: StructureResult,
    providers: ProviderSet,
    params: GroupingParams,
    *,
    overrides: Sequence[GroupOverride] = (),
    learned: LearnedGrouping | None = None,
) -> TopicResult:
    slug = doc.slug
    by_id = {b.id: b for b in blocks}
    body = sorted(
        (b for b in blocks if not is_header_footer(b)), key=lambda b: ids.block_sort_key(b.id)
    )
    pos = {b.id: i for i, b in enumerate(body)}
    stats = GroupStats()
    captions = bound_captions(blocks)
    summaries = block_summaries(blocks, structure, captions, params.summary_tokens)
    group_title = {g.id: g.title for g in structure.groups}

    asm = Assembly(placed={}, reasons={}, titles={}, slugs={}, sources={})
    for b in body:
        asm.placed[b.id] = None
        asm.reasons[b.id] = (
            UnassignedReason.no_text if is_no_text(b) else UnassignedReason.low_similarity
        )
    cand_ids = [b.id for b in body if not is_no_text(b)]
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None
    dim = 0
    decisions: list[StragglerDecision] = []
    c: np.ndarray | None = None
    row_of: dict[str, int] = {}

    if cand_ids:
        embedder = _provider(providers, Task.embeddings)
        try:
            v = embed_blocks(
                embedder,
                cand_ids,
                [summaries[i] for i in cand_ids],
                prefix=params.embed_prefix,
                batch=params.embed_batch,
            )
        except TopicFailure as exc:
            status, error = "failed", str(exc)
            for b in body:
                asm.reasons[b.id] = UnassignedReason.topic_failed
        else:
            dim = int(v.shape[1])
            c = center(v)
            row_of = {bid: r for r, bid in enumerate(cand_ids)}
            chat = _provider(providers, Task.grouping)
            examples = pick_examples(learned, slug, MAX_EXAMPLES)
            clusters = cluster(
                c, cand_ids, params, learned.do_not_merge if learned is not None else ()
            )
            keys = [f"c{i + 1:02d}" for i in range(len(clusters))]
            cents = np.vstack([centroid(c, m) for m in clusters])
            raw_slugs: dict[str, str] = {}
            for i, (key, m) in enumerate(zip(keys, clusters, strict=True)):
                for r in m:
                    asm.placed[cand_ids[r]] = key
                heads = rank_headings([group_title[structure.section_of[cand_ids[r]]] for r in m])
                sims = np.round(c[m] @ cents[i], 9)
                near = sorted(range(len(m)), key=lambda j: (-float(sims[j]), cand_ids[m[j]]))
                samples = [summaries[cand_ids[m[j]]] for j in near[: params.name_sample]]
                named = name_topic(chat, heads, samples, number=i + 1, examples=examples)
                asm.titles[key] = named.title
                raw_slugs[key] = named.slug
                asm.sources[key] = named.source
                if named.source == TitleSource.fallback:
                    stats.llm_fallbacks += 1
            in_cluster = {r for m in clusters for r in m}
            decisions = _place_stragglers(
                c,
                cand_ids,
                summaries,
                in_cluster,
                cents,
                keys,
                asm.titles,
                chat,
                params,
                examples,
                stats,
            )
            for d in decisions:
                asm.placed[d.block_id] = d.topic_key
                if d.topic_key is None:
                    asm.reasons[d.block_id] = UnassignedReason.low_similarity
            _bind(asm, captions, structure)
            _dissolve_small(asm)
            # unique slugs in final-id order (first member in block order)
            alive = sorted(asm.members().items(), key=lambda kv: min(pos[b] for b in kv[1]))
            used: set[str] = set()
            for key, _ in alive:
                s = ids.make_unique_slug(raw_slugs[key], used)
                used.add(s)
                asm.slugs[key] = s

    applied, stale, moved = apply_overrides(asm, overrides)
    _dissolve_small(asm)

    # -- final ids and groups -----------------------------------------------------------------
    members = {k: sorted(v, key=lambda b: pos[b]) for k, v in asm.members().items()}
    order = sorted(members, key=lambda k: pos[members[k][0]])
    final_id = {k: ids.group_id(slug, "topic", i + 1) for i, k in enumerate(order)}
    if len(order) > 998:
        raise GroupingError(f"{slug}: {len(order)} topics exceed the id space")

    def make_group(
        gid: str,
        title: str,
        gslug: str,
        bids: list[str],
        coh: float | None,
        unassigned: bool,
    ) -> Group:
        pages, figs = _page_figures([by_id[b] for b in bids])
        return Group(
            id=gid,
            view=GroupView.topic,
            doc_id=slug,
            title=title,
            slug=gslug,
            block_ids=bids,
            page_ranges=page_ranges(pages),
            section_ids=sorted(
                {structure.section_of[b] for b in bids if b in structure.section_of}
            ),
            parent_id=None,
            level=0,
            section_number=None,
            cohesion=coh,
            is_unassigned=unassigned,
            block_count=len(bids),
            figure_count=figs,
        )

    t000_ids = [b.id for b in body if asm.placed[b.id] is None]
    groups = [
        make_group(
            ids.group_id(slug, "topic", 0), UNASSIGNED_TITLE, ids.UNASSIGNED, t000_ids, None, True
        )
    ]
    sources: dict[str, TitleSource] = {groups[0].id: TitleSource.fallback}
    for k in order:
        rows = [row_of[b] for b in members[k] if b in row_of]
        coh = cohesion(c, rows) if c is not None else 0.0
        groups.append(make_group(final_id[k], asm.titles[k], asm.slugs[k], members[k], coh, False))
        sources[final_id[k]] = asm.sources[k]

    entries = [
        UnassignedEntry(block_id=b.id, view=GroupView.topic, reason=UnassignedReason.header_footer)
        for b in sorted(blocks, key=lambda b: ids.block_sort_key(b.id))
        if is_header_footer(b)
    ] + [UnassignedEntry(block_id=b, view=GroupView.topic, reason=asm.reasons[b]) for b in t000_ids]
    entries.sort(key=lambda e: ids.block_sort_key(e.block_id))

    records = []
    for d in decisions:
        if d.block_id in moved:
            continue
        placed_key = asm.placed[d.block_id]
        records.append(
            StragglerRecord(
                block_id=d.block_id,
                topic_id=None if placed_key is None else final_id[placed_key],
                similarity=max(-1.0, min(1.0, d.similarity)),
                by=d.by,
            )
        )
    records.sort(key=lambda r: ids.block_sort_key(r.block_id))
    return TopicResult(
        topics=groups,
        unassigned=entries,
        stragglers=records,
        title_sources=sources,
        status=status,
        error=error,
        embedding_dim=dim,
        overrides_applied=applied,
        overrides_stale=stale,
        stats=stats,
    )
