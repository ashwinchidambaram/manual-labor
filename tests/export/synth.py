"""Hand-built assemble inputs: no parser, no database. One document `doc`, ids b-doc-p001-NN."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from manuallabor import ids
from manuallabor.cleanup.types import ArticleAttachments, AttachFile, Attachment
from manuallabor.contracts.block import Block
from manuallabor.contracts.config import ProjectConfig
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import (
    ArticleSplit,
    AttachRule,
    BlockStatus,
    BlockType,
    DocKind,
    Extraction,
    GroupView,
    TitleSource,
    UnassignedReason,
)
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.group import (
    Group,
    GroupOverlap,
    GroupsFile,
    UnassignedEntry,
)
from manuallabor.contracts.manifest import ManifestLearning
from manuallabor.export.assemble import assemble
from manuallabor.export.types import (
    ActiveOverride,
    Assembled,
    AssembleInputs,
    DocInput,
    FigureData,
)
from manuallabor.grouping.structure import page_ranges
from manuallabor.grouping.types import default_params
from tests.conftest import make_block

SLUG = "doc"
CLOCK = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)


def bid(n: int, page: int = 1) -> str:
    return f"b-{SLUG}-p{page:03d}-{n:02d}"


def fid(n: int, page: int = 1, slug: str = SLUG) -> str:
    return f"FIG-{slug}-p{page:03d}-{n:02d}"


def blk(
    n: int,
    text: str = "Text.",
    *,
    type: BlockType = BlockType.paragraph,
    status: BlockStatus = BlockStatus.approved,
    clean: str | None = None,
    page: int = 1,
    **kw: object,
) -> Block:
    if type == BlockType.figure:
        kw["figure_id"] = fid(n, page)
        text = ""
    if status == BlockStatus.edited and clean is None:
        clean = text
    return make_block(text, n=n, page=page, type=type, status=status, clean_text=clean, **kw)  # type: ignore[arg-type]


def flag(n: int, target: str, status: str = "open") -> Flag:
    return Flag.model_validate(
        {
            "id": f"flag-{n:06d}",
            "target_id": target,
            "category": "wrong_text",
            "status": status,
            "created_at": CLOCK,
            "resolved_at": CLOCK if status == "resolved" else None,
        }
    )


def override(
    action_id: int,
    reason: str = "reviewed offline",
    target: str | None = None,
    flag_id: str | None = None,
) -> ActiveOverride:
    return ActiveOverride(
        action_id=action_id, ts=CLOCK, reason=reason, target_id=target, flag_id=flag_id
    )


def figure_data(
    n: int,
    *,
    page: int = 1,
    caption: str | None = "Figure 1. A pump.",
    generated: str | None = None,
    canonical: str | None = None,
    caption_block: str | None = None,
    svg: bool = False,
    slug: str = SLUG,
) -> FigureData:
    fig = fid(n, page, slug)
    if canonical is None:
        file, svg_file = f"{fig}.png", f"{fig}.svg"
    else:
        cslug = ids.parse_figure_id(canonical)[0]
        file, svg_file = f"../{cslug}/{canonical}.png", f"../{cslug}/{canonical}.svg"
    rec = FigureRecord(
        id=fig,
        file=file,
        svg=svg_file if svg else None,
        source_doc=slug,
        product_model=None,
        page=page,
        bbox=None,
        extraction=Extraction.vector if svg else Extraction.native,
        width=10,
        height=10,
        phash="0" * 16,
        caption_original=caption,
        description_generated=generated,
        tags=[],
        articles=[],
        attach_rule=AttachRule.none,
        confidence=1.0,
        review=BlockStatus.queued,
    )
    base = Path("/nonexistent")
    return FigureData(
        record=rec,
        caption_block_id=caption_block,
        canonical=canonical,
        png=base / file,
        svg=(base / svg_file) if svg else None,
    )


def att(
    figure: str,
    rule: AttachRule = AttachRule.proximity,
    anchor: str | None = None,
) -> Attachment:
    return Attachment(figure_id=figure, rule=rule, confidence=0.9, anchor_block_id=anchor)


def _groups(
    blocks: Sequence[Block],
    levels: Mapping[str, int],
    sections: Mapping[str, str],
    topics: Mapping[str, tuple[str, list[str]]] | None,
    unassigned_topic: Sequence[str],
) -> GroupsFile:
    body = [b for b in blocks if b.type not in (BlockType.header, BlockType.footer)]
    hf = [b.id for b in blocks if b.type in (BlockType.header, BlockType.footer)]
    by_id = {b.id: b for b in blocks}
    entries: list[tuple[str, str | None, int, str | None, list[Block]]] = []
    cur: list[Block] | None = None
    front: list[Block] = []
    for b in body:
        if b.id in levels:
            cur = [b]
            entries.append((b.raw_text, sections.get(b.id), levels[b.id], b.id, cur))
        elif cur is None:
            front.append(b)
        else:
            cur.append(b)
    structure: list[Group] = []
    titles: dict[str, TitleSource] = {}
    sec_of: dict[str, str] = {}
    n = 0
    if front:
        n += 1
        gid = ids.group_id(SLUG, "structure", n)
        structure.append(_group(gid, GroupView.structure, "Front matter", "front-matter", front, 1))
        titles[gid] = TitleSource.fallback
        sec_of.update({b.id: gid for b in front})
    stack: list[tuple[int, str]] = []
    for title, num, level, _head, members in entries:
        n += 1
        gid = ids.group_id(SLUG, "structure", n)
        while stack and stack[-1][0] >= level:
            stack.pop()
        g = _group(
            gid,
            GroupView.structure,
            title,
            ids.slugify(title) + f"-{n}",
            members,
            level,
            section_number=num,
            parent_id=stack[-1][1] if stack else None,
        )
        stack.append((level, gid))
        structure.append(g)
        titles[gid] = TitleSource.heading
        sec_of.update({b.id: gid for b in members})
    tspec = (
        dict(topics)
        if topics is not None
        else {"main": ("Main topic", [b.id for b in body if b.id not in unassigned_topic])}
    )
    topic_groups: list[Group] = []
    entries_un: list[UnassignedEntry] = []
    if unassigned_topic:
        topic_groups.append(
            _group(
                ids.group_id(SLUG, "topic", 0),
                GroupView.topic,
                "Unassigned blocks",
                "unassigned",
                [by_id[b] for b in unassigned_topic],
                0,
                is_unassigned=True,
            )
        )
        entries_un += [
            UnassignedEntry(
                block_id=b, view=GroupView.topic, reason=UnassignedReason.low_similarity
            )
            for b in unassigned_topic
        ]
    for t, (slug, (title, members)) in enumerate(tspec.items(), start=1):
        topic_groups.append(
            _group(
                ids.group_id(SLUG, "topic", t),
                GroupView.topic,
                title,
                slug,
                [by_id[b] for b in members],
                0,
            )
        )
    for b in hf:
        for view in (GroupView.structure, GroupView.topic):
            entries_un.append(
                UnassignedEntry(block_id=b, view=view, reason=UnassignedReason.header_footer)
            )
    counts: dict[tuple[str, str], int] = {}
    for tg in topic_groups:
        for b in tg.block_ids:
            s = sec_of.get(b)
            if s is not None:
                counts[(tg.id, s)] = counts.get((tg.id, s), 0) + 1
    return GroupsFile(
        doc_id=SLUG,
        algo_version="t",
        fingerprint="0" * 64,
        embedding_model="m",
        embedding_dim=0,
        grouping_model="mock",
        learning_snapshot="baseline",
        params=default_params(),
        structure=structure,
        topics=topic_groups,
        unassigned=entries_un,
        stragglers=[],
        overlap=[
            GroupOverlap(topic_id=a, section_id=b, blocks=c) for (a, b), c in sorted(counts.items())
        ],
        title_sources=titles,
        topic_status="ok",
        overrides_applied=0,
        overrides_stale=[],
    )


def _group(
    gid: str,
    view: GroupView,
    title: str,
    slug: str,
    members: Sequence[Block],
    level: int,
    *,
    section_number: str | None = None,
    parent_id: str | None = None,
    is_unassigned: bool = False,
) -> Group:
    return Group(
        id=gid,
        view=view,
        doc_id=SLUG,
        title=title,
        slug=slug,
        block_ids=[b.id for b in members],
        page_ranges=page_ranges([b.page for b in members]),
        level=level,
        section_number=section_number,
        parent_id=parent_id,
        is_unassigned=is_unassigned,
        block_count=len(members),
        figure_count=sum(1 for b in members if b.type == BlockType.figure),
    )


def synth_inputs(
    blocks: Sequence[Block],
    *,
    levels: Mapping[str, int] | None = None,
    sections: Mapping[str, str] | None = None,
    topics: Mapping[str, tuple[str, list[str]]] | None = None,
    unassigned_topic: Sequence[str] = (),
    figures: Sequence[FigureData] = (),
    attach: Mapping[str, Sequence[Attachment]] | None = None,
    selected: set[str] | None = None,
    flags: Sequence[Flag] = (),
    overrides: Sequence[ActiveOverride] = (),
    split: ArticleSplit = ArticleSplit.per_topic,
    title: str | None = "Doc Title",
    product_model: str | None = None,
    scope_extra: set[str] | None = None,
) -> AssembleInputs:
    blocks = list(blocks)
    gf = _groups(blocks, levels or {}, sections or {}, topics, unassigned_topic)
    doc = Document(
        slug=SLUG,
        sha256="a" * 64,
        filename="doc.pdf",
        title=title,
        product_model=product_model,
        kind=DocKind.born_digital_pdf,
        page_count=max([b.page for b in blocks] + [1]),
        block_ids=[b.id for b in blocks],
    )
    body = {b.id for b in blocks if b.type not in (BlockType.header, BlockType.footer)}
    sel = body if selected is None else selected
    af = AttachFile(
        doc_id=SLUG,
        algo_version="t",
        fingerprint="0" * 64,
        article_split=split,
        articles=[
            ArticleAttachments(article_id=a, figures=list(v)) for a, v in (attach or {}).items()
        ],
        unattached=[],
        unresolved_refs=[],
        overrides_applied=0,
        overrides_stale=[],
    )
    scope = set(sel) | (scope_extra or set())
    return AssembleInputs(
        config=ProjectConfig(name="Synthetic"),
        split=split,
        docs={
            SLUG: DocInput(
                doc=doc,
                blocks=blocks,
                groups=gf,
                attach=af,
                figures={f.record.id: f for f in figures},
                selected=set(sel),
                scope=scope,
            )
        },
        flags=list(flags),
        overrides=list(overrides),
        models={},
        learning=ManifestLearning(),
        tool_version="0.0.0-test",
    )


def run(inp: AssembleInputs) -> Assembled:
    return assemble(inp, CLOCK)
