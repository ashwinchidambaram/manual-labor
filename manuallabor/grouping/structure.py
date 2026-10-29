"""Structure view: the heading tree of a document, one group per heading node (design §2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from manuallabor import ids
from manuallabor.contracts.block import Block
from manuallabor.contracts.document import Document
from manuallabor.contracts.enums import BlockType, GroupView, TitleSource, UnassignedReason
from manuallabor.contracts.group import Group, PageRange, UnassignedEntry
from manuallabor.grouping.types import (
    MAX_GROUPS,
    PAGE_WINDOW,
    STRUCTURE_TITLE_MAX,
    GroupingError,
    SectionNode,
    StructureResult,
)
from manuallabor.parse.text import CAPTION_RE, collapse_ws

HF_TYPES = (BlockType.header, BlockType.footer)
DEMOTE_INSIDE = 0.8
FRONT_MATTER = "Front matter"


def is_header_footer(b: Block) -> bool:
    return b.type in HF_TYPES


def page_ranges(pages: Sequence[int]) -> list[PageRange]:
    """Sorted distinct pages merged into runs: [1,2,3,5] -> [1-3],[5-5]."""
    out: list[PageRange] = []
    for p in sorted(set(pages)):
        if out and p == out[-1].end + 1:
            out[-1] = PageRange(start=out[-1].start, end=p)
        else:
            out.append(PageRange(start=p, end=p))
    return out


def _inside_ratio(inner: list[float], outer: list[float]) -> float:
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    if area <= 0:
        return 0.0
    w = min(inner[2], outer[2]) - max(inner[0], outer[0])
    h = min(inner[3], outer[3]) - max(inner[1], outer[1])
    if w <= 0 or h <= 0:
        return 0.0
    return (w * h) / area


def _demoted(b: Block, containers: dict[int, list[list[float]]]) -> bool:
    text = collapse_ws(b.raw_text)
    if text == "":  # D1
        return True
    if CAPTION_RE.match(text):  # D3
        return True
    if b.bbox is not None:  # D2
        for box in containers.get(b.page, ()):
            if _inside_ratio(b.bbox, box) >= DEMOTE_INSIDE:
                return True
    return False


def _level(b: Block, prev: int | None) -> int:
    if b.section_number is not None:
        return min(6, len(b.section_number.split(".")))
    if b.heading_level is not None:
        return b.heading_level
    return prev if prev is not None else 1


@dataclass
class _Entry:
    title: str
    base: str | None  # slug base; None -> slugify(title)
    number: str | None
    parent: int | None
    depth: int
    source: TitleSource
    own: list[Block]


def build_structure(doc: Document, blocks: Sequence[Block]) -> StructureResult:
    slug = doc.slug
    ordered = sorted(blocks, key=lambda b: (b.reading_order, ids.block_sort_key(b.id)))
    unassigned = [
        UnassignedEntry(
            block_id=b.id, view=GroupView.structure, reason=UnassignedReason.header_footer
        )
        for b in sorted(ordered, key=lambda b: ids.block_sort_key(b.id))
        if is_header_footer(b)
    ]
    body = [b for b in ordered if not is_header_footer(b)]

    containers: dict[int, list[list[float]]] = {}
    for b in body:
        if b.type in (BlockType.figure, BlockType.table) and b.bbox is not None:
            containers.setdefault(b.page, []).append(list(b.bbox))

    # -- nodes --------------------------------------------------------------------------------
    nodes: list[SectionNode] = []
    node_at: dict[str, int] = {}
    stack: list[int] = []
    prev_level: int | None = None
    for b in body:
        if b.type != BlockType.heading or _demoted(b, containers):
            continue
        level = _level(b, prev_level)
        prev_level = level
        while stack and nodes[stack[-1]].level >= level:
            stack.pop()
        node = SectionNode(
            block_id=b.id,
            title=collapse_ws(b.raw_text)[:STRUCTURE_TITLE_MAX],
            level=level,
            section_number=b.section_number,
            parent=stack[-1] if stack else None,
            depth=len(stack) + 1,
        )
        node_at[b.id] = len(nodes)
        stack.append(len(nodes))
        nodes.append(node)

    # -- membership ---------------------------------------------------------------------------
    entries: list[_Entry] = []
    if nodes:
        front: list[Block] = []
        cur: int | None = None
        node_entry: dict[int, int] = {}
        pending: list[list[Block]] = []
        for b in body:
            n = node_at.get(b.id)
            if n is not None:
                node_entry[n] = len(pending)
                pending.append([b])
                cur = len(pending) - 1
            elif cur is None:
                front.append(b)
            else:
                pending[cur].append(b)
        offset = 1 if front else 0
        if front:
            entries.append(
                _Entry(FRONT_MATTER, "front-matter", None, None, 1, TitleSource.fallback, front)
            )
        for i, nd in enumerate(nodes):
            parent = None if nd.parent is None else node_entry[nd.parent] + offset
            entries.append(
                _Entry(
                    nd.title,
                    None,
                    nd.section_number,
                    parent,
                    nd.depth,
                    TitleSource.heading,
                    pending[i],
                )
            )
    elif body:
        last = max((b.page for b in blocks), default=1)
        windows: dict[int, list[Block]] = {}
        for b in body:
            windows.setdefault((b.page - 1) // PAGE_WINDOW, []).append(b)
        for w in sorted(windows):
            start = w * PAGE_WINDOW + 1
            end = min(start + PAGE_WINDOW - 1, max(last, start))
            title = f"Pages {start}–{end}"
            base = f"pages-{start:03d}-{end:03d}"
            entries.append(_Entry(title, base, None, None, 1, TitleSource.fallback, windows[w]))

    if len(entries) > MAX_GROUPS:
        raise GroupingError(
            f"{slug}: {len(entries)} structure groups exceed the {MAX_GROUPS} limit"
        )

    # -- groups -------------------------------------------------------------------------------
    groups: list[Group] = []
    used: set[str] = set()
    section_of: dict[str, str] = {}
    path_of: dict[str, list[str]] = {}
    sources: dict[str, TitleSource] = {}
    heading_of: dict[str, str] = {}
    gids = [ids.group_id(slug, "structure", i + 1) for i in range(len(entries))]
    for i, e in enumerate(entries):
        title, own, parent = e.title, e.own, e.parent
        gslug = ids.make_unique_slug(e.base or ids.slugify(title), used)
        used.add(gslug)
        own_sorted = sorted(own, key=lambda b: ids.block_sort_key(b.id))
        groups.append(
            Group(
                id=gids[i],
                view=GroupView.structure,
                doc_id=slug,
                title=title,
                slug=gslug,
                block_ids=[b.id for b in own_sorted],
                page_ranges=page_ranges([b.page for b in own]),
                section_ids=[],
                parent_id=None if parent is None else gids[parent],
                level=e.depth,
                section_number=e.number,
                cohesion=None,
                is_unassigned=False,
                block_count=len(own),
                figure_count=sum(1 for b in own if b.type == BlockType.figure),
            )
        )
        sources[gids[i]] = e.source
        if e.source == TitleSource.heading:
            heading_of[gids[i]] = e.own[0].id
        trail = [title]
        p = parent
        while p is not None:
            trail.append(entries[p].title)
            p = entries[p].parent
        trail.reverse()
        for b in own:
            section_of[b.id] = gids[i]
            path_of[b.id] = trail
    return StructureResult(
        groups=groups,
        unassigned=unassigned,
        section_of=section_of,
        path_of=path_of,
        title_sources=sources,
        heading_of=heading_of,
    )
