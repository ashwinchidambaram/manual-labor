"""Topic view: cluster, name, place stragglers, bind captions and headings, apply overrides
(design §3). One topic set per document."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.cluster.hierarchy import linkage

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
from manuallabor.grouping.cluster import _split_tree, center, centroid, cluster, cohesion
from manuallabor.grouping.embed import embed_blocks
from manuallabor.grouping.label import (
    NamedTopic,
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
    MAX_GROUPS,
    MIN_FINAL_TOPIC_BLOCKS,
    MIN_TOPIC_BLOCKS,
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


def _name_cluster(
    chat: Provider,
    c: np.ndarray,
    cand_ids: Sequence[str],
    summaries: Mapping[str, str],
    group_title: Mapping[str, str],
    structure: StructureResult,
    rows: Sequence[int],
    cent: np.ndarray,
    number: int,
    params: GroupingParams,
    examples: Sequence[Mapping[str, str]],
    stats: GroupStats,
) -> NamedTopic:
    heads = rank_headings([group_title[structure.section_of[cand_ids[r]]] for r in rows])
    sims = np.round(c[list(rows)] @ cent, 9)
    near = sorted(range(len(rows)), key=lambda j: (-float(sims[j]), cand_ids[rows[j]]))
    samples = [summaries[cand_ids[rows[j]]] for j in near[: params.name_sample]]
    named = name_topic(chat, heads, samples, number=number, examples=examples)
    if named.source == TitleSource.fallback:
        stats.llm_fallbacks += 1
    return named


def _enforce_do_not_merge(
    asm: Assembly,
    pairs: Sequence[tuple[str, str]],
    movable: set[str],
    c: np.ndarray,
    row_of: Mapping[str, int],
    params: GroupingParams,
) -> None:
    """The cannot-link constraint on the FINAL assignment. Clustering keeps the pairs apart, but
    a straggler or a bound heading/caption may land beside its partner. Such a block (the
    later one of the pair when both can move) takes its next-best topic that holds none of its
    partners, else goes to t000 with reason `do_not_merge`."""
    partners: dict[str, set[str]] = {}
    for a, b in pairs:
        if a != b and a in asm.placed and b in asm.placed:
            partners.setdefault(a, set()).add(b)
            partners.setdefault(b, set()).add(a)
    if not partners:
        return
    ordered = sorted(partners, key=ids.block_sort_key)
    for _ in range(sum(len(v) for v in partners.values()) + 1):
        hit: tuple[str, str] | None = None
        for a in ordered:
            ka = asm.placed[a]
            if ka is None:
                continue
            for b in sorted(partners[a], key=ids.block_sort_key):
                if ids.block_sort_key(b) > ids.block_sort_key(a) and asm.placed[b] == ka:
                    hit = (a, b)
                    break
            if hit:
                break
        if hit is None:
            return
        a, b = hit
        mover = b if b in movable or a not in movable else a
        banned = {asm.placed[p] for p in partners[mover]} - {None}
        members = asm.members()
        target: str | None = None
        if mover in row_of:
            ranked: list[tuple[float, str]] = []
            for k, mem in members.items():
                rows = [row_of[x] for x in mem if x != mover and x in row_of]
                if k in banned or not rows:
                    continue
                ranked.append((float(c[row_of[mover]] @ centroid(c, rows)), k))
            ranked.sort(key=lambda t: (-t[0], t[1]))
            target = next((k for sim, k in ranked if sim >= params.t_candidate), None)
        asm.placed[mover] = target
        if target is None:
            asm.reasons[mover] = UnassignedReason.do_not_merge
        else:
            asm.reasons.pop(mover, None)


def _reading_chunks(members: Sequence[str], cap: int) -> list[list[str]]:
    """Even consecutive chunks, none above `cap` and (for len > cap) none below cap/2."""
    n = -(-len(members) // cap)
    size, extra = divmod(len(members), n)
    out: list[list[str]] = []
    at = 0
    for i in range(n):
        end = at + size + (1 if i < extra else 0)
        out.append(list(members[at:end]))
        at = end
    return out


def _split_oversized(
    members: Sequence[str],
    pos: Mapping[str, int],
    c: np.ndarray,
    row_of: Mapping[str, int],
    cap: int,
    cannot: Sequence[tuple[str, str]],
) -> list[list[str]]:
    """Chunks of at most `cap` blocks: along the dendrogram of the members' embeddings, or
    (when it cannot be built, or a chunk is still too big) by reading order."""
    mem = sorted(members, key=lambda b: pos[b])
    with_row = [b for b in mem if b in row_of]
    chunks: list[list[str]]
    if len(with_row) >= 2:
        local = {b: i for i, b in enumerate(with_row)}
        y = np.clip(np.round(_pdist(c[[row_of[b] for b in with_row]]), 9), 0.0, 2.0) + 0.0
        z = linkage(y, method="average")
        pairs = [(local[a], local[b]) for a, b in cannot if a in local and b in local]
        n = len(with_row)
        parts = _split_tree(z, n, np.zeros(n, dtype=np.int64), cap, pairs)
        groups = sorted((sorted(with_row[i] for i in p) for p in parts), key=lambda g: pos[g[0]])
        firsts = [pos[g[0]] for g in groups]
        chunks = [list(g) for g in groups]
        for b in mem:  # blocks without an embedding row ride with the preceding chunk
            if b in row_of:
                continue
            idx = max((i for i, f in enumerate(firsts) if f <= pos[b]), default=0)
            chunks[idx].append(b)
    else:
        chunks = [mem]
    if any(len(ch) < MIN_TOPIC_BLOCKS for ch in chunks):
        chunks = [mem]  # a lopsided tree (e.g. all-identical rows): fall back to reading order
    out: list[list[str]] = []
    for ch in chunks:
        out.extend(
            [sorted(ch, key=lambda b: pos[b])]
            if len(ch) <= cap
            else _reading_chunks(sorted(ch, key=lambda b: pos[b]), cap)
        )
    return out


def _pdist(m: np.ndarray) -> np.ndarray:
    from scipy.spatial.distance import pdist

    return np.asarray(pdist(m, "cosine"))


def _straggler_records(
    decisions: Sequence[StragglerDecision],
    asm: Assembly,
    final_id: Mapping[str, str],
    c: np.ndarray | None,
    row_of: Mapping[str, int],
    moved: set[str],
    origin: Mapping[str, str],
    origin_centroid: Mapping[str, np.ndarray],
) -> list[StragglerRecord]:
    """One record per straggler (similarity to the topic it FINALLY sits in) and per cluster
    member that fell out of a dissolved topic (similarity to the cluster it came from)."""
    final_members = asm.members()
    out: list[StragglerRecord] = []
    seen: set[str] = set()
    for d in decisions:
        seen.add(d.block_id)
        if d.block_id in moved:
            continue
        key = asm.placed[d.block_id]
        sim = d.similarity
        if key is not None and key != d.topic_key and c is not None and d.block_id in row_of:
            rows = [row_of[b] for b in final_members[key] if b in row_of]
            if rows:
                sim = round(float(c[row_of[d.block_id]] @ centroid(c, rows)), 9)
        out.append(
            StragglerRecord(
                block_id=d.block_id,
                topic_id=None if key is None else final_id[key],
                similarity=max(-1.0, min(1.0, sim)),
                by=d.by,
            )
        )
    if c is not None:
        for b, k in origin.items():
            if b in seen or b in moved or asm.placed.get(b) is not None:
                continue
            sim = round(float(c[row_of[b]] @ origin_centroid[k]), 9)
            out.append(
                StragglerRecord(
                    block_id=b, topic_id=None, similarity=max(-1.0, min(1.0, sim)), by="centroid"
                )
            )
    out.sort(key=lambda r: ids.block_sort_key(r.block_id))
    return out


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
    origin: dict[str, str] = {}
    origin_centroid: dict[str, np.ndarray] = {}

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
                    origin[cand_ids[r]] = key
                origin_centroid[key] = cents[i]
                named = _name_cluster(
                    chat, c, cand_ids, summaries, group_title, structure, m, cents[i],
                    i + 1, params, examples, stats,
                )  # fmt: skip
                asm.titles[key] = named.title
                raw_slugs[key] = named.slug
                asm.sources[key] = named.source
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
            cannot = list(learned.do_not_merge) if learned is not None else []
            movable = (
                {d.block_id for d in decisions}
                | set(captions.values())
                | set(structure.heading_of.values())
            )
            _enforce_do_not_merge(asm, cannot, movable, c, row_of, params)
            number = len(keys)
            for key, mem in sorted(asm.members().items()):
                if len(mem) <= params.max_topic_blocks:
                    continue
                chunks = _split_oversized(mem, pos, c, row_of, params.max_topic_blocks, cannot)
                asm.titles.pop(key, None)
                asm.sources.pop(key, None)
                raw_slugs.pop(key, None)
                for ch in chunks:
                    number += 1
                    nk = f"c{number:02d}"
                    rows = [row_of[b] for b in ch if b in row_of]
                    cent = centroid(c, rows) if rows else cents[0]
                    named = _name_cluster(
                        chat, c, cand_ids, summaries, group_title, structure, rows, cent,
                        number, params, examples, stats,
                    )  # fmt: skip
                    asm.titles[nk], raw_slugs[nk], asm.sources[nk] = (
                        named.title, named.slug, named.source,
                    )  # fmt: skip
                    for bid in ch:
                        asm.placed[bid] = nk
            _dissolve_small(asm)
            # unique slugs in final-id order (first member in block order)
            alive = sorted(asm.members().items(), key=lambda kv: min(pos[b] for b in kv[1]))
            used: set[str] = set()
            for key, _ in alive:
                s = ids.make_unique_slug(raw_slugs[key], used)
                used.add(s)
                asm.slugs[key] = s

    applied, stale, moved = apply_overrides(asm, overrides)
    before = dict(asm.slugs)
    _dissolve_small(asm)
    gone = {slug for key, slug in before.items() if key not in asm.slugs}
    if gone:  # an override aimed at a topic that no longer exists did not take effect
        late = [
            i
            for i, o in enumerate(overrides)
            if i not in stale and (o.to_topic_slug if o.kind == "move" else o.topic_slug) in gone
        ]
        stale = sorted([*stale, *late])
        applied -= len(late)

    # -- final ids and groups -----------------------------------------------------------------
    members = {k: sorted(v, key=lambda b: pos[b]) for k, v in asm.members().items()}
    order = sorted(members, key=lambda k: pos[members[k][0]])
    final_id = {k: ids.group_id(slug, "topic", i + 1) for i, k in enumerate(order)}
    if len(order) > MAX_GROUPS - 1:
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

    records = _straggler_records(
        decisions, asm, final_id, c, row_of, moved, origin, origin_centroid
    )
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
