"""Assemble articles, figures and the manifest from loaded inputs (design 11 section 3). Pure:
the same inputs and clock always produce the same bytes."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from manuallabor import ids
from manuallabor.cleanup.attach import build_articles
from manuallabor.cleanup.types import Attachment
from manuallabor.contracts.article import (
    DECIDED_BY,
    TEXT_PREFIX,
    ArticleFrontmatter,
    ArticleReview,
    ArticleReviewCounts,
    BlockReview,
    FigurePlacement,
    FigureReview,
    ReviewStatus,
)
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ModelRef
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import (
    ArticleSplit,
    AttachRule,
    BlockStatus,
    BlockType,
    GroupView,
    Task,
    UnassignedReason,
)
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import dump_json
from manuallabor.contracts.manifest import (
    BlockAccounting,
    Manifest,
    ManifestArticle,
    ManifestFigure,
    ManifestProject,
    Override,
    ReviewStats,
)
from manuallabor.export.gate import export_gate
from manuallabor.export.markers import (
    SOURCE_MARKER_RE,
    marker_line,
    misplaced_markers,
    needs_marker,
    tally_markers,
)
from manuallabor.export.readme import render_readme
from manuallabor.export.render import (
    alt_text,
    figure_line,
    heading_line,
    render_list,
    yaml_frontmatter,
)
from manuallabor.export.types import (
    MAX_ARTICLE_BYTES,
    ActiveOverride,
    Assembled,
    AssembleInputs,
    BodyPart,
    BuiltArticle,
    BuiltFigure,
    DocInput,
    ExportError,
    FigureData,
    GateLocked,
)
from manuallabor.state.models import ExportReviewSummary

__all__ = ["CONTRIBUTING", "assemble", "block_text", "truncate_clock"]

CONTRIBUTING: Final = frozenset(
    {BlockStatus.auto_approved, BlockStatus.approved, BlockStatus.edited}
)
_WS_RE: Final = re.compile(r"\s+")
_END: Final = 10**9
UNASSIGNED_TITLE: Final = "Unassigned blocks"


def truncate_clock(dt: datetime) -> datetime:
    """Whole seconds, UTC (`generated_at` is one value per export)."""
    return dt.astimezone(UTC).replace(microsecond=0)


def block_text(b: Block) -> str:
    """P1: the cleaned text (the human text for an edited block), the raw text only when
    cleanup never touched the block."""
    return b.clean_text if b.clean_text is not None else b.raw_text


def _collapse(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def _section_key(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split("."))


def _topic_titles(d: DocInput) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in d.groups.topics:
        out[ids.article_id(d.doc.slug, t.slug)] = UNASSIGNED_TITLE if t.is_unassigned else t.title
    return out


def _heading_levels(d: DocInput, order: dict[str, int]) -> dict[str, int]:
    """Block id -> structure depth for the heading blocks that are section nodes."""
    out: dict[str, int] = {}
    for g in d.groups.structure:
        if d.groups.title_sources.get(g.id) != "heading" or not g.block_ids:
            continue
        head = min(g.block_ids, key=lambda b: order.get(b, _END))
        out[head] = g.level
    return out


def _is_empty(b: Block) -> bool:
    """P4: decided on the source text, so a block with source words is never dropped as
    `empty` because its cleaned text came out blank."""
    return b.type != BlockType.figure and _collapse(b.raw_text) == ""


def _render_block(b: Block, levels: dict[str, int]) -> str:
    t = block_text(b)
    if b.type == BlockType.heading and b.id in levels:
        return heading_line(t, levels[b.id])
    if b.type == BlockType.list:
        return render_list(t)
    return t


class _Ctx:
    """Everything the per-article step needs across documents."""

    def __init__(self, inp: AssembleInputs, generated_at: datetime) -> None:
        self.inp = inp
        self.generated_at = generated_at
        blocks_by_doc = {s: d.blocks for s, d in inp.docs.items()}
        scope = {s: d.scope for s, d in inp.docs.items()}
        self.gate = export_gate(blocks_by_doc, scope, inp.flags, inp.overrides)
        if self.gate.blockers:
            raise GateLocked(self.gate.open_flags, self.gate.queued, self.gate.blockers)
        self.status: dict[str, BlockStatus] = {
            b.id: b.status for d in inp.docs.values() for b in d.blocks
        }
        self.referenced_by: dict[str, set[str]] = {}  # exported figure id -> article ids
        self.assignments: dict[str, str] = {}
        self.reasons: dict[str, str] = {}
        self.pages: set[tuple[str, int]] = set()


def _figure_parts(
    d: DocInput,
    art_id: str,
    atts: list[Attachment],
    kept_order: dict[str, int],
    has_part: set[str],
) -> list[tuple[tuple[int, int, int], BodyPart, str]]:
    """(sort key, part, figure id) for every attachment of the article (design 3.3)."""
    out: list[tuple[tuple[int, int, int], BodyPart, str]] = []
    fig_block = {str(b.figure_id): b.id for b in d.blocks if b.figure_id is not None}
    for idx, a in enumerate(atts):
        fd = d.figures.get(a.figure_id)
        if fd is None:
            raise ExportError(f"{art_id}: {a.figure_id} is attached but has no sidecar")
        key = (_END, 0, idx)
        if a.rule in (AttachRule.caption_ref, AttachRule.caption_match, AttachRule.human):
            if a.anchor_block_id is not None and a.anchor_block_id in has_part:
                key = (kept_order[a.anchor_block_id], 1, idx)
            elif a.rule == AttachRule.human and a.anchor_block_id is None:
                key = _proximity_key(fd, fig_block.get(a.figure_id), kept_order, has_part, idx)
        else:
            key = _proximity_key(fd, fig_block.get(a.figure_id), kept_order, has_part, idx)
        canon = fd.canonical or fd.record.id
        path = f"images/{ids.parse_figure_id(canon)[0]}/{canon}.png"
        alt = alt_text(fd.record.id, fd.record.caption_original, fd.record.description_generated)
        part = BodyPart("figure", None, fd.record.id, figure_line(alt, path))
        out.append((key, part, fd.record.id))
    return out


def _proximity_key(
    fd: FigureData,
    own_block: str | None,
    kept_order: dict[str, int],
    has_part: set[str],
    idx: int,
) -> tuple[int, int, int]:
    if fd.caption_block_id is not None and fd.caption_block_id in has_part:
        return (kept_order[fd.caption_block_id], 1, idx)
    if own_block is not None and own_block in kept_order:
        return (kept_order[own_block], -1, idx)
    return (_END, 0, idx)


def _check_every_selected_block_placed(
    d: DocInput, selected: set[str], members: dict[str, list[str]], ctx: _Ctx
) -> None:
    """A selected block lands in an article, or is unassigned for a reason the grouping
    recorded (a topic-view header/footer entry). Anything else is an assembly error: calling it
    `not_selected` would drop selected content silently."""
    placed = {b for m in members.values() for b in m}
    recorded_hf = {
        u.block_id
        for u in d.groups.unassigned
        if u.view == GroupView.topic and u.reason == UnassignedReason.header_footer
    }
    missing: list[str] = []
    for b in sorted(selected - placed, key=ids.block_sort_key):
        if b in recorded_hf:
            ctx.reasons[b] = "header_footer"
        else:
            missing.append(b)
    if missing:
        shown = ", ".join(missing[:20]) + (
            f" (+{len(missing) - 20} more)" if len(missing) > 20 else ""
        )
        raise ExportError(
            f"{d.doc.slug}: {len(missing)} selected block(s) in no article and not unassigned "
            f"with a recorded reason (groups.json does not place them): {shown}"
        )


def _build_doc_articles(ctx: _Ctx, d: DocInput) -> list[BuiltArticle]:
    inp = ctx.inp
    slug = d.doc.slug
    by_id = {b.id: b for b in d.blocks}
    order = {b.id: b.reading_order for b in d.blocks}
    hf = {b.id for b in d.blocks if b.type in (BlockType.header, BlockType.footer)}
    selected = {b for b in d.selected if b in by_id and b not in hf}
    members = build_articles(slug, d.groups, selected, inp.split, order)
    _check_every_selected_block_placed(d, selected, members, ctx)
    levels = _heading_levels(d, order)
    sec_of = {b: g for g in d.groups.structure for b in g.block_ids}
    titles = _topic_titles(d)
    doc_title = _collapse(d.doc.title or "") or Path(d.doc.filename).stem
    attach = {a.article_id: a.figures for a in d.attach.articles}
    built: list[BuiltArticle] = []

    kept_of: dict[str, list[Block]] = {}
    for art_id, member_ids in members.items():
        kept: list[Block] = []
        for bid in member_ids:
            b = by_id[bid]
            if b.status == BlockStatus.rejected:
                ctx.reasons[bid] = "rejected"
            elif _is_empty(b):
                ctx.reasons[bid] = "empty"
            elif b.status not in CONTRIBUTING and bid not in ctx.gate.covered:
                raise ExportError(f"{bid} is {b.status.value} and not covered by an override")
            else:
                kept.append(b)
        if kept:
            kept_of[art_id] = kept
    placements = _placements(d, set(kept_of))

    for art_id, kept in kept_of.items():
        title = _collapse(doc_title if inp.split == ArticleSplit.per_document else titles[art_id])
        title = title or doc_title
        kept_order = {b.id: b.reading_order for b in kept}
        if SOURCE_MARKER_RE.search(title):
            raise ExportError(
                f"{art_id}: the article title {title!r} contains an HTML comment opening "
                "'ml:', which would read as a review marker (design 11 section 20); rename the "
                "topic in Scope"
            )
        rendered = {b.id: _render_block(b, levels) for b in kept if b.type != BlockType.figure}
        entries = [_review_entry(ctx, d, b, placements, rendered.get(b.id)) for b in kept]
        entry_of = {e.block_id: e for e in entries}
        text_parts: list[tuple[tuple[int, int, int], BodyPart]] = []
        for b in kept:
            if b.type == BlockType.figure:
                continue
            if SOURCE_MARKER_RE.search(rendered[b.id]):
                raise ExportError(
                    f"{b.id}: its text contains an HTML comment opening 'ml:', which would read "
                    "as a review marker (design 11 section 20); edit the block in Verify"
                )
            e = entry_of[b.id]
            # section 20.11: every paragraph's marker on the line directly above it
            mk = marker_line(e) if needs_marker(e) else None
            part = BodyPart("block", b.id, None, rendered[b.id], marker=mk)
            text_parts.append(((b.reading_order, 0, 0), part))
        has_part = {p.block_id for _, p in text_parts if p.kind == "block" and p.block_id}
        figs = _figure_parts(d, art_id, attach.get(art_id, []), kept_order, has_part)
        merged: list[tuple[tuple[int, int, int], BodyPart]] = [
            *text_parts,
            *((k, p) for k, p, _ in figs),
        ]
        merged.sort(key=lambda kp: kp[0])
        parts = [p for _, p in merged]
        fig_ids = [p.figure_id for p in parts if p.kind == "figure" and p.figure_id]
        for fid in fig_ids:
            ctx.referenced_by.setdefault(fid, set()).add(art_id)

        sections = sorted(
            {g.section_number for b in kept if (g := sec_of.get(b.id)) and g.section_number},
            key=_section_key,
        )
        pages = sorted({b.page for b in kept})
        # section 20.11: the front matter counts are the sidecar's, category for category (an
        # override-covered block, e.g. approved but with an open flag, counts once, as overridden)
        counts = _review_counts(entries)
        fm = ArticleFrontmatter(
            id=art_id,
            title=title,
            source_doc=slug,
            source_file=d.doc.filename,
            product_model=d.doc.product_model,
            pages=pages,
            sections=sections,
            figures=fig_ids,
            blocks=len(kept),
            review=counts,
            generated_at=ctx.generated_at,
        )
        head = yaml_frontmatter(fm) + "\n# " + title + "\n"
        text = head + ("\n" + "\n\n".join(p.unit for p in parts) + "\n" if parts else "")
        _refuse_visible_markers(art_id, text[len(yaml_frontmatter(fm)) :])
        review = ArticleReview(
            article_id=art_id,
            article=f"articles/{art_id}.md",
            generated_at=ctx.generated_at,
            counts=counts,
            blocks=entries,
        )
        for b in kept:
            ctx.assignments[b.id] = art_id
            ctx.pages.add((slug, b.page))
        built.append(
            BuiltArticle(
                id=art_id,
                path=f"articles/{art_id}.md",
                text=text,
                frontmatter=fm,
                title=title,
                block_ids=[b.id for b in kept],
                figure_ids=fig_ids,
                review=review,
                review_path=f"articles/{art_id}.review.json",
                body_parts=parts,
            )
        )
    return built


def _placements(d: DocInput, written: set[str]) -> dict[str, list[FigurePlacement]]:
    """Figure id -> its attachments in the written articles of the document, by article id:
    where its figure line appears (design 11 section 20.3)."""
    out: dict[str, list[FigurePlacement]] = {}
    for arts in sorted(d.attach.articles, key=lambda x: x.article_id):
        if arts.article_id not in written:
            continue
        for a in arts.figures:
            out.setdefault(a.figure_id, []).append(
                FigurePlacement(article_id=arts.article_id, rule=a.rule, confidence=a.confidence)
            )
    return out


def _review_entry(
    ctx: _Ctx,
    d: DocInput,
    b: Block,
    placements: dict[str, list[FigurePlacement]],
    part_text: str | None,
) -> BlockReview:
    """Who decided that `b` goes out, as the front matter counts it: an override-covered
    block is `overridden` whatever its status; otherwise the overlay status decides."""
    fig = None
    if b.figure_id is not None:
        fig = FigureReview(figure_id=b.figure_id, placements=placements.get(b.figure_id, []))
    ov = ctx.gate.covered.get(b.id)
    status: ReviewStatus
    at: datetime | None = None
    confidence: float | None = None
    edited_by: Literal["person", "agent_proposal"] | None = None
    if ov is not None:
        status, at = "overridden", ov.ts
    elif b.status == BlockStatus.auto_approved:
        status, confidence = "auto_approved", b.confidence
    elif b.status in (BlockStatus.approved, BlockStatus.edited):
        status = "approved" if b.status == BlockStatus.approved else "edited"
        dec = d.decisions.get(b.id)
        if dec is None:  # the overlay derives approved/edited only from a decision
            raise ExportError(f"{b.id} is {status} but no decision record says who decided it")
        at = dec.at
        if status == "edited":
            edited_by = dec.edited_by or "person"
    else:  # unreachable: assembly refuses an uncovered non-contributing block first
        raise ExportError(f"{b.id} is {b.status.value} and not covered by an override")
    return BlockReview(
        block_id=b.id,
        type=b.type,
        page=b.page,
        status=status,
        decided_by=DECIDED_BY[status],
        at=at,
        confidence=confidence,
        edited_by=edited_by,
        reason=ov.reason if ov is not None else None,
        flag_id=_override_flag(ctx, b.id, ov) if ov is not None else None,
        figure=fig,
        text_sha256=(
            hashlib.sha256(part_text.encode("utf-8")).hexdigest() if part_text is not None else None
        ),
        text=part_text[:TEXT_PREFIX] if part_text is not None else None,
        placement="figure" if b.type == BlockType.figure else "paragraph",
    )


def _override_flag(ctx: _Ctx, block_id: str, ov: ActiveOverride) -> str | None:
    """The flag an override record names for a block: the flag a flag override names when it is
    an open flag on this block (so flag and reason come from the same decision), else the
    block's first open flag (a blanket override), else None. The gate records, for a block with
    open flags, the latest override that covers a flag (design 11 section 20.10)."""
    if ov.flag_id is not None and ov.flag_id in ctx.gate.block_flags.get(block_id, ()):
        return ov.flag_id
    return ctx.gate.open_flag_of.get(block_id)


def _review_counts(entries: list[BlockReview]) -> ArticleReviewCounts:
    n = Counter(e.status for e in entries)
    return ArticleReviewCounts(
        auto_approved=n["auto_approved"],
        approved=n["approved"],
        edited=n["edited"],
        overridden=n["overridden"],
    )


_HOLDER: Final = {
    "fence": "code fence",
    "code_block": "indented code block",
    "html_block": "raw HTML block",
    "inline": "paragraph",
    "text": "line of text",
}
_BLOCK_IN_MARKER: Final = re.compile(r"block: (b-[a-z0-9-]+-p\d{3,}-\d{2,})")


def _refuse_visible_markers(art_id: str, body: str) -> None:
    """Design 11 section 20.6: a marker a renderer would show (swallowed by a construct the
    source text leaves open) refuses the export, naming the marked block."""
    bad = misplaced_markers(body)
    if not bad:
        return
    line, kind = bad[0]
    m = _BLOCK_IN_MARKER.search(line)
    block = m.group(1) if m else "a block"
    more = f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""
    raise ExportError(
        f"{art_id}: the review marker of {block} would render as text{more}: it falls inside a "
        f"{_HOLDER.get(kind, kind)} that an earlier block of the article leaves open (an unclosed "
        "code fence or raw HTML block in the source text). Every paragraph carries a marker "
        "(design 11 section 20.11), so edit or reject the block that opens it in Verify."
    )


def _exported_figures(ctx: _Ctx) -> list[BuiltFigure]:
    """Figures referenced by a written article, plus the canonical of every duplicate (P5)."""
    inp = ctx.inp
    by_fig: dict[str, FigureData] = {
        fid: fd for d in inp.docs.values() for fid, fd in d.figures.items()
    }
    owner = {fid: d for d in inp.docs.values() for fid in d.figures}
    wanted: set[str] = set(ctx.referenced_by)
    for fid in list(wanted):
        canon = by_fig[fid].canonical
        if canon is not None:
            if canon not in by_fig:
                raise ExportError(f"{fid}: canonical figure {canon} is not in the project")
            wanted.add(canon)
    block_of = {str(b.figure_id): b for d in inp.docs.values() for b in d.blocks if b.figure_id}
    out: list[BuiltFigure] = []
    for fid in sorted(wanted, key=ids.block_sort_key):
        fd = by_fig[fid]
        rec = fd.record
        blk = block_of.get(fid)
        review = rec.review
        if blk is not None and blk.id in owner[fid].scope:
            review = blk.status
        data = rec.model_dump(mode="json")
        data["articles"] = sorted(ctx.referenced_by.get(fid, set()))
        data["review"] = review.value
        sidecar = FigureRecord.model_validate(data)
        slug = ids.parse_figure_id(fid)[0]
        dup = fd.canonical is not None
        out.append(
            BuiltFigure(
                id=fid,
                sidecar_path=f"images/{slug}/{fid}.json",
                sidecar=sidecar,
                canonical=fd.canonical,
                png=None if dup else fd.png,
                png_path=None if dup else f"images/{slug}/{fid}.png",
                svg=None if dup or fd.svg is None else fd.svg,
                svg_path=None if dup or fd.svg is None else f"images/{slug}/{fid}.svg",
            )
        )
    return out


def _models(inp: AssembleInputs) -> dict[Task, ModelRef]:
    out: dict[Task, ModelRef] = {}
    for task in Task:
        ref = inp.models.get(task.value)
        if ref is not None:
            out[task] = ModelRef(provider=ref[0], model=ref[1])
            continue
        cfg_ref = inp.config.model_for(task)
        if cfg_ref is not None and task.value in {"cleanup", "grouping", "embeddings", "vision"}:
            out[task] = ModelRef(provider=cfg_ref.provider, model=cfg_ref.model)
    return out


def _manifest(
    ctx: _Ctx,
    articles: list[BuiltArticle],
    figures: list[BuiltFigure],
) -> Manifest:
    inp = ctx.inp
    docs: list[Document] = [d.doc for _, d in sorted(inp.docs.items())]
    block_status: Counter[str] = Counter()
    numbers_verified: list[str] = []
    for d in inp.docs.values():
        for b in d.blocks:
            block_status[b.status.value] += 1
            if b.numbers_verified:
                numbers_verified.append(b.id)
    fixed_reason: dict[str, str] = {}
    types: dict[str, BlockType] = {}
    for d in inp.docs.values():
        for b in d.blocks:
            types[b.id] = b.type
            selected = b.id in d.selected
            if b.type in (BlockType.header, BlockType.footer):
                fixed_reason[b.id] = "header_footer"
            elif not selected:
                fixed_reason[b.id] = "not_selected"
    assignments: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for d in inp.docs.values():
        for bid in d.doc.block_ids:
            if bid in ctx.assignments:
                assignments[bid] = ctx.assignments[bid]
                continue
            assignments[bid] = ids.UNASSIGNED
            why = fixed_reason.get(bid) or ctx.reasons.get(bid)
            if why is None:  # selected, yet in no article and without a reason
                raise ExportError(f"{bid} is selected but was placed in no article")
            reasons[bid] = why
    overrides: list[Override] = []
    for a in articles:
        for bid in a.block_ids:
            ov: ActiveOverride | None = ctx.gate.covered.get(bid)
            if ov is not None:
                overrides.append(
                    Override(
                        target_id=bid,
                        flag_id=_override_flag(ctx, bid, ov),
                        reason=ov.reason,
                        at=ov.ts,
                    )
                )
    overrides.sort(key=lambda o: ids.block_sort_key(str(o.target_id)))
    total = len(assignments)
    stats = ReviewStats(
        total_blocks=total,
        auto_approved=block_status[BlockStatus.auto_approved.value],
        approved=block_status[BlockStatus.approved.value],
        edited=block_status[BlockStatus.edited.value],
        flagged=block_status[BlockStatus.flagged.value],
        rejected=block_status[BlockStatus.rejected.value],
        queued=block_status[BlockStatus.queued.value],
        overrides=len(overrides),
        numbers_verified_blocks=numbers_verified,
    )
    return Manifest.model_validate(
        {
            "project": ManifestProject(
                name=inp.config.name, tool_version=inp.tool_version, generated_at=ctx.generated_at
            ),
            "docs": docs,
            "articles": [
                ManifestArticle(
                    id=a.id,
                    path=a.path,
                    title=a.title,
                    source_doc=a.frontmatter.source_doc,
                    block_ids=a.block_ids,
                    figures=a.figure_ids,
                    pages=a.frontmatter.pages,
                    sections=a.frontmatter.sections,
                    review_sidecar=a.review_path,
                )
                for a in articles
            ],
            "figures": [
                ManifestFigure(
                    id=f.id,
                    sidecar=f.sidecar_path,
                    file=f.sidecar.file,
                    source_doc=f.sidecar.source_doc,
                    duplicate_of=f.canonical,
                )
                for f in figures
            ],
            "review_stats": stats,
            "models": _models(inp),
            "threshold": inp.config.threshold,
            "article_split": inp.split,
            "overrides": overrides,
            "accounting": BlockAccounting(
                total_blocks=total,
                assignments=assignments,
                unassigned_reasons=reasons,  # type: ignore[arg-type]
            ),
            "learning": inp.learning,
        }
    )


def _review_summary(
    ctx: _Ctx, articles: list[BuiltArticle], manifest: Manifest
) -> ExportReviewSummary:
    """Design 11 section 14: every exported block in exactly one bucket (an override-covered
    block only as an override, like the frontmatter), and the rest of the parsed blocks by
    their manifest reason, so the Export screen's numbers add up to what was parsed."""
    n: Counter[str] = Counter()
    for a in articles:
        for bid in a.block_ids:
            n["overrides" if bid in ctx.gate.covered else ctx.status[bid].value] += 1
    stray = set(n) - {"auto_approved", "approved", "edited", "overrides"}
    if stray:  # unreachable: assembly refuses an uncovered non-contributing block
        raise ExportError(f"exported blocks with status {sorted(stray)}")
    acc = manifest.accounting
    return ExportReviewSummary(
        blocks=sum(n.values()),
        auto_approved=n["auto_approved"],
        approved=n["approved"],
        edited=n["edited"],
        overrides=n["overrides"],
        numbers_verified=len(manifest.review_stats.numbers_verified_blocks),
        total_blocks=acc.total_blocks,
        left_out=dict(sorted(Counter(acc.unassigned_reasons.values()).items())),
    )


def assemble(inp: AssembleInputs, clock: datetime) -> Assembled:
    """Build everything the zip holds. Raises GateLocked when the export gate is closed."""
    generated_at = truncate_clock(clock)
    ctx = _Ctx(inp, generated_at)
    articles: list[BuiltArticle] = []
    for slug in sorted(inp.docs):
        articles.extend(_build_doc_articles(ctx, inp.docs[slug]))
    articles.sort(key=lambda a: a.id)
    figures = _exported_figures(ctx)
    manifest = _manifest(ctx, articles, figures)
    review = _review_summary(ctx, articles, manifest)
    warnings = [
        f"article {a.id} is {len(a.text.encode('utf-8'))} bytes (over {MAX_ARTICLE_BYTES})"
        for a in articles
        if len(a.text.encode("utf-8")) > MAX_ARTICLE_BYTES
    ]
    readme = render_readme(manifest, tally_markers([a.review for a in articles]))
    files: dict[str, str | Path] = {"README.md": readme, "manifest.json": dump_json(manifest)}
    for a in articles:
        files[a.path] = a.text
        files[a.review_path] = dump_json(a.review)
    for f in figures:
        files[f.sidecar_path] = dump_json(f.sidecar)
        if f.png is not None and f.png_path is not None:
            files[f.png_path] = f.png
        if f.svg is not None and f.svg_path is not None:
            files[f.svg_path] = f.svg
    return Assembled(
        articles=articles,
        figures=figures,
        manifest=manifest,
        readme=readme,
        pages_covered=len(ctx.pages),
        warnings=warnings,
        generated_at=generated_at,
        review=review,
        files=dict(sorted(files.items())),
    )
