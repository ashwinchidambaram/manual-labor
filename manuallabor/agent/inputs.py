"""Eligible items, the input bundle of one item and its candidates (design 10 sections 3.1-3.3).

Everything here is deterministic and reads files (plus, on the service side, the DB for flags,
proposals and the text the reviewer saw). Candidates carry plain facts only; the model chooses
among them and never invents an id or a coordinate."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manuallabor import ids
from manuallabor.agent.data import (
    canon,
    figure_facts,
    file_sha,
    target_slug,
)
from manuallabor.agent.rounds import priors_for
from manuallabor.agent.types import (
    AGENT_MAX_READER_CHARS,
    BBOX_PAD_PT,
    HINTS_MAX,
    MAX_BBOX_CANDIDATES,
    MAX_CANDIDATES,
    NOTE_MAX,
    AgentInput,
    AgentItem,
    BboxCandidate,
    Skip,
)
from manuallabor.calibration.types import (
    AGENT_EXAMPLES_K,
    AgentExample,
    LearnedAgent,
    LearnedCalibration,
)
from manuallabor.cleanup.attach import build_articles
from manuallabor.cleanup.llm import truncate_lines
from manuallabor.cleanup.refs import caption_number, find_refs, is_chaptered
from manuallabor.contracts.block import Block, TableData, VisionReading
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.enums import (
    BlockType,
    DocKind,
    FlagCategory,
    FlagStatus,
    ProposalKind,
    ProposalStatus,
)
from manuallabor.contracts.proposal import Proposal
from manuallabor.parse import geometry as g
from manuallabor.project import ProjectPaths
from manuallabor.scoring.numeric import numeric_specs_for  # noqa: F401  (re-exported for tests)
from manuallabor.state.data import ProjectData
from manuallabor.state.review import display_text, load_review_blocks
from manuallabor.state.store import Store

__all__ = [
    "KIND_OF",
    "TEXT_TYPES",
    "basis_sha256",
    "bbox_candidates",
    "build_input",
    "eligible_items",
    "kind_for",
    "make_reason_of",
    "unsupported_reason",
]

TEXT_TYPES = frozenset(
    {BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.caption, BlockType.other}
)
KIND_OF: dict[FlagCategory, ProposalKind] = {
    FlagCategory.wrong_text: ProposalKind.text,
    FlagCategory.table_structure: ProposalKind.cells,
    FlagCategory.missing_figure: ProposalKind.attach,
    FlagCategory.wrong_grouping: ProposalKind.regroup,
    FlagCategory.bad_crop: ProposalKind.bbox,
}


# -- what is supported ---------------------------------------------------------------------------


def kind_for(
    category: FlagCategory, block: Block, *, figure_target: bool, doc_kind: DocKind
) -> tuple[ProposalKind | None, str | None]:
    """(kind, None) when the category x target pair is in the matrix of design 10 section 3.3,
    else (None, why not)."""
    if category == FlagCategory.wrong_text:
        if figure_target or block.type not in TEXT_TYPES:
            return None, "wrong_text needs a text block"
        if len(block.raw_text) > AGENT_MAX_READER_CHARS:
            return None, f"text is longer than {AGENT_MAX_READER_CHARS} characters"
    elif category == FlagCategory.table_structure:
        if block.type != BlockType.table or block.table is None:
            return None, "table_structure needs a table block with cells"
        if len(block.raw_text) > AGENT_MAX_READER_CHARS:
            return None, f"table text is longer than {AGENT_MAX_READER_CHARS} characters"
    elif category == FlagCategory.missing_figure:
        if not (figure_target or block.type in (*TEXT_TYPES, BlockType.table)):
            return None, "missing_figure needs a text block or a figure"
    elif category == FlagCategory.wrong_grouping:
        if block.type in (BlockType.header, BlockType.footer):
            return None, "headers and footers are not grouped"
    elif category == FlagCategory.bad_crop:
        if not figure_target:
            return None, "bad_crop needs a figure"
        if doc_kind == DocKind.docx or block.bbox is None:
            return None, "only PDF figures have a crop box"
    return KIND_OF[category], None


def unsupported_reason(
    category: FlagCategory, block: Block, *, figure_target: bool, doc_kind: DocKind
) -> str | None:
    return kind_for(category, block, figure_target=figure_target, doc_kind=doc_kind)[1]


# -- eligibility ---------------------------------------------------------------------------------


def make_reason_of(store: Store) -> Callable[[Proposal], tuple[str | None, datetime]]:
    """The reviewer's reason (from the reject action) and decision time of a settled proposal."""

    def reason_of(p: Proposal) -> tuple[str | None, datetime]:
        aid = store.proposal_row_action(p.id)
        act = store.get_action(aid) if aid is not None else None
        if act is None:
            return None, p.created_at
        reason = act.payload.get("reason")
        return (str(reason) if reason else None), act.ts

    return reason_of


def eligible_items(
    paths: ProjectPaths,
    store: Store,
    data: ProjectData,
    cfg: ProjectConfig,
    *,
    docs: Sequence[str] | None = None,
    flag_ids: Sequence[str] | None = None,
    include_pending: bool = False,
) -> tuple[list[AgentItem], list[Skip]]:
    """Open flags the agent can work on now, in flag order, and the skipped ones with why."""
    items: list[AgentItem] = []
    skips: list[Skip] = []
    reason_of = make_reason_of(store)
    overlays: dict[str, dict[str, Block]] = {}
    scopes: dict[str, set[str]] = {}
    ready: dict[str, bool] = {}
    slugs = set(paths.list_slugs())
    all_props = store.proposals()
    by_flag: dict[str, list[Proposal]] = {}
    for p in all_props:
        by_flag.setdefault(p.flag_id, []).append(p)
    for f in store.flags(FlagStatus.open):
        if flag_ids is not None and f.id not in flag_ids:
            continue
        slug = target_slug(f.target_id)
        if docs is not None and slug not in docs:
            continue
        if slug not in slugs:
            skips.append(Skip(f.id, f.target_id, "out_of_scope", "document is not in the project"))
            continue
        if slug not in ready:
            rd = data.readiness(slug)
            ready[slug] = rd.state == "ready" and not rd.stale
        if not ready[slug]:
            skips.append(Skip(f.id, f.target_id, "stale_doc", "document is not up to date"))
            continue
        if slug not in overlays:
            overlays[slug] = {b.id: b for b in load_review_blocks(paths, store, slug)}
            scopes[slug] = data.scope_ids(slug)
        figure_target = f.target_id.startswith("FIG-")
        block = None
        if figure_target:
            ff = figure_facts(paths, data, f.target_id)
            block = overlays[slug].get(ff.block.id) if ff is not None else None
        else:
            block = overlays[slug].get(f.target_id)
        if block is None:
            skips.append(Skip(f.id, f.target_id, "unsupported", "target not found"))
            continue
        if block.id not in scopes[slug]:
            skips.append(Skip(f.id, f.target_id, "out_of_scope", "target is not in review scope"))
            continue
        figure_target = figure_target or block.type == BlockType.figure
        mine = by_flag.get(f.id, [])
        if any(p.status == ProposalStatus.pending for p in mine) and not include_pending:
            skips.append(Skip(f.id, f.target_id, "pending", "a proposal is waiting"))
            continue
        priors = priors_for(mine, reason_of)
        if len(priors) >= cfg.agent.max_rounds:
            skips.append(
                Skip(f.id, f.target_id, "max_rounds", f"{len(priors)} proposals already settled")
            )
            continue
        kind, why = kind_for(
            f.category,
            block,
            figure_target=figure_target,
            doc_kind=data.document(slug).kind,
        )
        if kind is None:
            skips.append(Skip(f.id, f.target_id, "unsupported", why))
            continue
        current = display_text(block) if kind in (ProposalKind.text, ProposalKind.cells) else None
        items.append(
            AgentItem(
                flag_id=f.id,
                category=f.category,
                note=f.note,
                target_id=f.target_id,
                doc_id=slug,
                round=len(priors) + 1,
                priors=priors,
                current_text=current,
                basis_sha256=basis_sha256(paths, data, f.target_id, kind, current, None),
            )
        )
    return items, skips


# -- the basis hash ------------------------------------------------------------------------------


def basis_sha256(
    paths: ProjectPaths,
    data: ProjectData,
    target_id: str,
    kind: ProposalKind,
    current_text: str | None,
    vision: VisionReading | None,
) -> str:
    """sha256 of the inputs every recheck of this proposal depends on (design 10 section 3.9).
    Equal basis means the stored rechecks are still exact, so accept needs no model call."""
    slug = target_slug(target_id)
    dp = paths.doc(slug)
    payload: dict[str, Any] = {"kind": kind.value, "target": target_id}
    if kind in (ProposalKind.text, ProposalKind.cells):
        blk = next((b for b in data.raw_blocks(slug) if b.id == target_id), None)
        mb = next((b for b in data.machine_blocks(slug) if b.id == target_id), None)
        sf = data.score_file(slug)
        variants: list[Any] = []
        if sf is not None:
            for s in sf.blocks:
                if s.block_id == target_id and s.faithfulness is not None:
                    variants = [v.model_dump(mode="json") for v in s.faithfulness.numeric_variants]
        payload.update(
            {
                "raw_text": blk.raw_text if blk else None,
                "readers": dict(sorted(blk.raw_text_by_parser.items())) if blk else None,
                "display": current_text,
                "variants": variants,
                # N needs two attesters on a numeric-spec block, one otherwise
                "has_numeric_spec": mb.has_numeric_spec if mb else None,
                "table": blk.table.model_dump(mode="json") if blk and blk.table else None,
                "document": file_sha(dp.document),
                "vision": vision.model_dump(mode="json") if vision is not None else None,
            }
        )
    elif kind == ProposalKind.bbox:
        ff = figure_facts(paths, data, target_id)
        page = ff.block.page if ff is not None else 0
        payload.update(
            {
                "bbox": ff.bbox if ff is not None else None,
                "page_blocks": [
                    [b.id, b.type.value, b.bbox] for b in data.raw_blocks(slug) if b.page == page
                ],
            }
        )
    elif kind == ProposalKind.attach:
        sel = data.selection()
        payload.update(
            {
                "attach": file_sha(dp.attach),
                # the articles (attach_target, attach_evidence) are built from the topic view
                "groups": file_sha(dp.groups),
                "group_overrides": file_sha(dp.group_overrides),
                "selection": canon([sel.block_ids, sel.article_split.value, sel.active_view.value]),
            }
        )
    else:
        payload.update({"groups": file_sha(dp.groups), "overrides": file_sha(dp.group_overrides)})
    return canon(payload)


# -- learned layer (prompt only) ----------------------------------------------------------------


def load_learned_agent(paths: ProjectPaths, cfg: ProjectConfig) -> LearnedAgent | None:
    if not cfg.learning.enabled or not paths.learned_agent.is_file():
        return None
    try:
        return LearnedAgent.model_validate_json(paths.learned_agent.read_text(encoding="utf-8"))
    except ValueError:
        return None


def load_hints(paths: ProjectPaths, cfg: ProjectConfig) -> list[str]:
    """Learned OCR confusion pairs as prompt hints (never as evidence, never in a check)."""
    if not cfg.learning.enabled or not paths.learned_calibration.is_file():
        return []
    try:
        lc = LearnedCalibration.model_validate_json(
            paths.learned_calibration.read_text(encoding="utf-8")
        )
    except ValueError:
        return []
    rows = sorted(lc.confusions, key=lambda c: (-c.support, c.id))[:HINTS_MAX]
    return [f"{c.wrong!r} misread for {c.right!r} (n={c.support})" for c in rows]


_OUTCOME_RANK = {"accepted": 0, "edited": 1, "rejected": 2}


def pick_examples(
    learned: LearnedAgent | None, category: FlagCategory, block_type: str
) -> list[AgentExample]:
    if learned is None:
        return []
    rows = [e for e in learned.examples if e.category == category.value]
    rows.sort(key=lambda e: (e.block_type != block_type, _OUTCOME_RANK[e.outcome], e.id))
    return rows[:AGENT_EXAMPLES_K]


# -- doc embeddings (regroup candidates and the similarity check) -------------------------------


@dataclass
class DocEmbeddings:
    """Centered embedding space of one document (the module 4 space)."""

    row_of: dict[str, int]
    matrix: Any  # np.ndarray, centered rows

    def vec(self, block_id: str) -> Any | None:
        r = self.row_of.get(block_id)
        return None if r is None else self.matrix[r]

    def centroid_of(self, block_ids: Iterable[str]) -> Any | None:
        from manuallabor.grouping.cluster import centroid

        rows = [self.row_of[b] for b in block_ids if b in self.row_of]
        return centroid(self.matrix, rows) if rows else None


def doc_embeddings(
    paths: ProjectPaths, data: ProjectData, providers: Any, slug: str
) -> DocEmbeddings | None:
    """None when the document has no topic view or embedding fails (the caller degrades)."""
    from manuallabor.contracts.enums import Task
    from manuallabor.grouping.cluster import center
    from manuallabor.grouping.embed import embed_blocks
    from manuallabor.grouping.structure import build_structure, is_header_footer
    from manuallabor.grouping.summary import block_summaries, bound_captions, is_no_text
    from manuallabor.grouping.types import TopicFailure

    gf = data.groups(slug)
    if gf is None:
        return None
    blocks = data.raw_blocks(slug)
    doc = data.document(slug)
    structure = build_structure(doc, blocks)
    summaries = block_summaries(blocks, structure, bound_captions(blocks), gf.params.summary_tokens)
    cand = sorted(
        (b.id for b in blocks if not is_header_footer(b) and not is_no_text(b)),
        key=ids.block_sort_key,
    )
    if not cand:
        return None
    try:
        v = embed_blocks(
            providers.get(Task.embeddings),
            cand,
            [summaries[i] for i in cand],
            prefix=gf.params.embed_prefix,
            batch=gf.params.embed_batch,
        )
    except TopicFailure:
        return None
    return DocEmbeddings({b: i for i, b in enumerate(cand)}, center(v))


def cosine(a: Any, b: Any) -> float:
    import numpy as np

    return float(np.dot(a, b))


def topic_of(gf: Any, block_id: str) -> Any | None:
    return next((t for t in gf.topics if block_id in t.block_ids), None)


# -- bbox candidates -----------------------------------------------------------------------------

_BODY_TEXT = frozenset(
    {BlockType.paragraph, BlockType.list, BlockType.heading, BlockType.other, BlockType.table}
)


def _clip(box: Sequence[float], page: Sequence[float]) -> list[float] | None:
    b = [
        max(page[0], box[0]),
        max(page[1], box[1]),
        min(page[2], box[2]),
        min(page[3], box[3]),
    ]
    return g.qbox(b) if b[2] > b[0] and b[3] > b[1] else None


def _overlapping_text(box: Sequence[float], blocks: Sequence[Block], page: int) -> int:
    n = 0
    for b in blocks:
        if b.page != page or b.type not in _BODY_TEXT or b.bbox is None:
            continue
        a = g.area(b.bbox)
        if a > 0 and g.intersection(b.bbox, box) > 0.10 * a:
            n += 1
    return n


def bbox_candidates(
    paths: ProjectPaths, data: ProjectData, figure_id: str
) -> tuple[list[BboxCandidate], list[float] | None]:
    """c0 image placements, c1 drawing cluster, c2 caption gap, c3 padded current box
    (deduplicated at IoU >= 0.95, at most 6), and the page rect."""
    from manuallabor.figures.captions import find_captions
    from manuallabor.figures.decide import ink_drawings
    from manuallabor.figures.page_content import load_page_content

    ff = figure_facts(paths, data, figure_id)
    if ff is None or ff.bbox is None:
        return [], None
    slug = ids.parse_figure_id(figure_id)[0]
    doc = data.document(slug)
    blocks = data.raw_blocks(slug)
    cur = ff.bbox
    page_no = ff.block.page
    from manuallabor.parse.pdf_pymupdf import open_pdf

    with open_pdf(paths.source(doc.filename)) as pdf:
        pg = pdf[page_no - 1]
        pc = load_page_content(pdf, pg, has_text_layer=page_no not in doc.pages_without_text_layer)
    page = list(pc.page_rect)
    raw: list[tuple[str, str, list[float] | None, str | None]] = []
    imgs = [p.bbox for p in pc.placements if g.intersection(p.bbox, cur) > 0]
    raw.append(("c0", "images", g.union(imgs) if imgs else None, None))
    ink = ink_drawings(page, pc)
    seeds = [d.rect for d in ink if g.intersection(d.rect, cur) > 0]
    union_box: list[float] | None = None
    if seeds:
        union_box = g.union(seeds)
        for _ in range(20):
            grown = g.union(
                [
                    union_box,
                    *[d.rect for d in ink if g.intersection(d.rect, g.expand(union_box, 4)) > 0],
                ]
            )
            if grown == union_box:
                break
            union_box = grown
    raw.append(("c1", "drawings", union_box, None))
    cap = find_captions(blocks).get(figure_id)
    gap: list[float] | None = None
    cap_text: str | None = None
    if cap is not None:
        cb = next((b for b in blocks if b.id == cap.block_id), None)
        if cb is not None and cb.bbox is not None:
            cap_text = cap.text
            x0, x1 = min(cb.bbox[0], cur[0]), max(cb.bbox[2], cur[2])
            texts = [
                b
                for b in blocks
                if b.page == page_no and b.type in _BODY_TEXT and b.bbox is not None
            ]
            if cb.bbox[1] >= cur[3] - 1:  # caption below the figure
                above = [b.bbox[3] for b in texts if b.bbox is not None and b.bbox[3] <= cb.bbox[1]]
                top = max(above) if above else cur[1]
                gap = [x0, top, x1, cb.bbox[1]]
            else:  # caption above the figure
                below = [b.bbox[1] for b in texts if b.bbox is not None and b.bbox[1] >= cb.bbox[3]]
                bottom = min(below) if below else cur[3]
                gap = [x0, cb.bbox[3], x1, bottom]
    raw.append(("c2", "caption_gap", gap, cap_text))
    raw.append(("c3", "padded", g.expand(cur, BBOX_PAD_PT), None))
    out: list[BboxCandidate] = []
    for cid, kind, box, caption in raw:
        if box is None:
            continue
        clipped = _clip(box, page)
        if clipped is None or any(g.iou(clipped, c.bbox) >= 0.95 for c in out):
            continue
        out.append(
            BboxCandidate(
                id=cid,
                bbox=clipped,
                kind=kind,
                area_frac=round(g.area(clipped) / g.area(page), 4) if g.area(page) > 0 else 0.0,
                overlaps_text_blocks=_overlapping_text(clipped, blocks, page_no),
                caption=caption,
            )
        )
    return out[:MAX_BBOX_CANDIDATES], page


# -- attach / regroup candidates ----------------------------------------------------------------


def _fig_caption(paths: ProjectPaths, slug: str, fid: str) -> tuple[bool, str | None]:
    """(has a sidecar and an image, original caption)."""
    ff = None
    sc = paths.figure_file(slug, fid, "json")
    if not sc.is_file():
        return False, None
    from manuallabor.contracts.figure import FigureRecord
    from manuallabor.contracts.io import read_json

    ff = read_json(sc, FigureRecord)
    return True, ff.caption_original


def _attached_figures(data: ProjectData, slug: str, article_ids: Iterable[str]) -> set[str]:
    af = data.attach(slug)
    if af is None:
        return set()
    want = set(article_ids)
    return {a.figure_id for art in af.articles if art.article_id in want for a in art.figures}


def attach_candidates_for_block(
    paths: ProjectPaths, data: ProjectData, slug: str, block: Block
) -> list[dict[str, Any]]:
    figs = [b for b in data.raw_blocks(slug) if b.type == BlockType.figure and b.figure_id]
    info: dict[str, tuple[str | None, int]] = {}
    for fb in figs:
        fid = str(fb.figure_id)
        ok, caption = _fig_caption(paths, slug, fid)
        if ok:
            info[fid] = (caption, fb.page)
    nums = {fid: caption_number(c) for fid, (c, _p) in info.items()}
    chaptered = is_chaptered(list(nums.values()))
    refs = {r.number for r in find_refs(block.raw_text, chaptered)}
    attached = _attached_figures(data, slug, data.articles_of(slug, block.id))
    out: list[dict[str, Any]] = []
    for fid in sorted(info):
        caption, page = info[fid]
        near = abs(page - block.page) <= 1
        referenced = nums[fid] is not None and nums[fid] in refs
        if (near or referenced) and fid not in attached:
            out.append({"id": fid, "caption": caption, "page": page})
    return out[:MAX_CANDIDATES]


def attach_candidates_for_figure(
    paths: ProjectPaths, data: ProjectData, slug: str, figure_id: str
) -> list[dict[str, Any]]:
    gf = data.groups(slug)
    ff = figure_facts(paths, data, figure_id)
    if gf is None or ff is None:
        return []
    sel = data.selection()
    selected = {b for b in sel.block_ids if ids.parse_block_id(b)[0] == slug}
    blocks = {b.id: b for b in data.raw_blocks(slug)}
    order = {b.id: b.reading_order for b in blocks.values()}
    arts = build_articles(slug, gf, selected, sel.article_split, order)
    caption = ff.record.caption_original if ff.record is not None else None
    num = caption_number(caption)
    chaptered = is_chaptered([caption_number(caption)])
    af = data.attach(slug)
    attached = (
        {
            art.article_id
            for art in af.articles
            if any(a.figure_id == figure_id for a in art.figures)
        }
        if af is not None
        else set()
    )
    titles = {ids.article_id(slug, t.slug): t.title for t in gf.topics}
    out: list[dict[str, Any]] = []
    for aid, members in arts.items():
        if aid in attached:
            continue
        mem = [blocks[m] for m in members if m in blocks]
        referenced = num is not None and any(
            r.number == num for b in mem for r in find_refs(b.raw_text, chaptered)
        )
        on_page = any(b.page == ff.block.page for b in mem)
        if referenced or on_page:
            out.append(
                {
                    "id": aid,
                    "title": titles.get(aid, data.document(slug).slug),
                    "pages": sorted({b.page for b in mem}),
                }
            )
    return out[:MAX_CANDIDATES]


def regroup_candidates(
    data: ProjectData, slug: str, block: Block, emb: DocEmbeddings | None
) -> list[dict[str, Any]]:
    gf = data.groups(slug)
    if gf is None:
        return []
    cur = topic_of(gf, block.id)
    pool = [t for t in gf.topics if not t.is_unassigned and (cur is None or t.id != cur.id)]
    vec = emb.vec(block.id) if emb is not None else None
    scored: list[tuple[float, str, Any]] = []
    for t in pool:
        cen = emb.centroid_of(t.block_ids) if emb is not None and vec is not None else None
        sim = cosine(vec, cen) if cen is not None else -2.0
        scored.append((-sim, t.slug, t))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [
        {
            "slug": t.slug,
            "title": t.title,
            "pages": sorted({p for r in t.page_ranges for p in range(r.start, r.end + 1)}),
        }
        for _s, _slug, t in scored[:MAX_CANDIDATES]
    ]


# -- the bundle ----------------------------------------------------------------------------------


def _candidate_text(kind: ProposalKind, cands: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """id -> the description evidence may be quoted from."""
    out: dict[str, str] = {}
    for c in cands:
        if kind == ProposalKind.bbox:
            out[str(c["id"])] = f"{c['id']} {c['kind']} bbox {c['bbox']}"
        elif kind == ProposalKind.regroup:
            out[str(c["slug"])] = f"{c['slug']} {c.get('title') or ''}".strip()
        else:
            label = c.get("caption") if "caption" in c else c.get("title")
            out[str(c["id"])] = f"{c['id']} {label or ''}".strip()
    return out


def _table_view(td: TableData) -> dict[str, Any]:
    grid: list[list[str]] = [["" for _ in range(td.n_cols)] for _ in range(td.n_rows)]
    for c in td.cells:
        grid[c.row][c.col] = c.text
    return {
        "n_rows": td.n_rows,
        "n_cols": td.n_cols,
        "rows": grid,
        "header_rows": sorted({c.row for c in td.cells if c.is_header}),
        "shape_by_parser": {k: [v.rows, v.cols] for k, v in sorted(td.shape_by_parser.items())},
    }


def build_input(
    paths: ProjectPaths,
    data: ProjectData,
    cfg: ProjectConfig,
    item: AgentItem,
    *,
    vision: VisionReading | None,
    emb: DocEmbeddings | None,
    learned: LearnedAgent | None,
    hints: Sequence[str],
) -> AgentInput:
    slug = item.doc_id
    figure_target = item.target_id.startswith("FIG-")
    kind = KIND_OF[item.category]
    ff = figure_facts(paths, data, item.target_id) if figure_target else None
    block_id = ff.block.id if ff is not None else item.target_id
    block = next((b for b in data.machine_blocks(slug) if b.id == block_id), None)
    if block is None:
        raise KeyError(block_id)
    readers = dict(sorted(block.raw_text_by_parser.items()))
    candidates: list[dict[str, Any]] = []
    page_rect: list[float] | None = None
    if kind == ProposalKind.attach:
        candidates = (
            attach_candidates_for_figure(paths, data, slug, item.target_id)
            if figure_target
            else attach_candidates_for_block(paths, data, slug, block)
        )
    elif kind == ProposalKind.regroup:
        candidates = regroup_candidates(data, slug, block, emb)
    elif kind == ProposalKind.bbox:
        bc, page_rect = bbox_candidates(paths, data, item.target_id)
        candidates = [c.model_dump(mode="json") for c in bc]
    cand_text = _candidate_text(kind, candidates)
    sf = data.score_file(slug)
    score = next((s for s in sf.blocks if s.block_id == block.id), None) if sf else None
    current = item.current_text if item.current_text is not None else ""

    def trunc(s: str) -> str:
        return truncate_lines(s, AGENT_MAX_READER_CHARS)

    bundle: dict[str, Any] = {
        "flag": {
            "id": item.flag_id,
            "category": item.category.value,
            "note": (item.note or "")[:NOTE_MAX] or None,
        },
        "target": {
            "id": item.target_id,
            "kind": "figure" if figure_target else "block",
            "doc_id": slug,
            "page": block.page,
            "block_type": block.type.value,
            "bbox": (ff.bbox if ff is not None else block.bbox),
        },
        "readers": {
            "raw_source": block.raw_source,
            "raw_text": trunc(block.raw_text),
            "raw_text_by_parser": {k: trunc(v) for k, v in readers.items()},
            "current": trunc(current),
        },
        "signals": [
            {"name": s.name.value, "value": s.value, "critical": s.critical, "detail": s.detail}
            for s in sorted(block.signals, key=lambda s: s.name.value)
        ],
        "numeric_specs": list(score.numeric_specs) if score is not None else [],
        "table": _table_view(block.table)
        if kind == ProposalKind.cells and block.table is not None
        else None,
        "vision": {"lines": vision.lines, "numbers": vision.numbers}
        if vision is not None and vision.outcome == "ok"
        else None,
        "candidates": candidates,
        "priors": [
            {
                "kind": p.kind.value,
                "proposal": truncate_lines(p.proposal_text, 1200),
                "reason": p.reason,
                "failed_checks": p.failed_checks,
            }
            for p in item.priors
        ],
        "examples": [
            e.model_dump(mode="json", exclude={"id"})
            for e in pick_examples(learned, item.category, block.type.value)
        ],
        "hints": list(hints),
    }
    image = None
    if cfg.agent.page_image and kind != ProposalKind.cells:
        image = render_page_image(paths, data, slug, block.page, candidates, kind)
    return AgentInput(
        item=item,
        kind=kind,
        bundle=bundle,
        raw_text=block.raw_text,
        raw_source=block.raw_source,
        readers=readers,
        current=current,
        candidates=candidates,
        candidate_text=cand_text,
        vision=vision,
        max_text=2 * len(block.raw_text) + 200,
        page_image=image,
        page_rect=page_rect,
    )


def render_page_image(
    paths: ProjectPaths,
    data: ProjectData,
    slug: str,
    page: int,
    candidates: Sequence[Mapping[str, Any]],
    kind: ProposalKind,
) -> bytes | None:
    """The page at 100 DPI (long side <= 1024 px), with candidate boxes drawn and labelled for
    bad_crop. Only sent when `agent.page_image` is on (the default agent model is text-only)."""
    import io

    from PIL import Image, ImageDraw

    from manuallabor.parse.pdf_pymupdf import open_pdf, pm

    doc = data.document(slug)
    if doc.kind == DocKind.docx:
        return None
    with open_pdf(paths.source(doc.filename)) as pdf:
        pix = pdf[page - 1].get_pixmap(dpi=100, colorspace=pm().csRGB)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    scale = 100 / 72
    if kind == ProposalKind.bbox:
        d = ImageDraw.Draw(img)
        for c in candidates:
            x0, y0, x1, y1 = (float(v) * scale for v in c["bbox"])
            d.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)
            d.text((x0 + 3, y0 + 3), str(c["id"]), fill=(255, 0, 0))
    long_side = max(img.size)
    if long_side > 1024:
        k = 1024 / long_side
        img = img.resize((round(img.width * k), round(img.height * k)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class RunCache:
    """Per-run memo of document embeddings (one embedding pass per document)."""

    emb: dict[str, DocEmbeddings | None] = field(default_factory=dict)

    def get(
        self, paths: ProjectPaths, data: ProjectData, providers: Any, slug: str
    ) -> DocEmbeddings | None:
        if slug not in self.emb:
            self.emb[slug] = doc_embeddings(paths, data, providers, slug)
        return self.emb[slug]
