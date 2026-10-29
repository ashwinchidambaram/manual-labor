"""Selection operations and the scope summary (design §5). Pure except load/save."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import ArticleSplit, BlockStatus, BlockType, GroupView
from manuallabor.contracts.group import Group, GroupsFile
from manuallabor.contracts.io import read_json, write_json
from manuallabor.contracts.selection import ReviewLoad, ScopeSummary, Selection
from manuallabor.project import ProjectPaths

HF_TYPES = (BlockType.header, BlockType.footer)


def _with(sel: Selection, **changes: object) -> Selection:
    data = sel.model_dump(mode="json")
    data.update(changes)
    return Selection.model_validate(data)


def select_blocks(sel: Selection, block_ids: Iterable[str]) -> Selection:
    return _with(sel, block_ids=[*sel.block_ids, *block_ids])


def deselect_blocks(sel: Selection, block_ids: Iterable[str]) -> Selection:
    drop = set(block_ids)
    return _with(sel, block_ids=[b for b in sel.block_ids if b not in drop])


def select_group(sel: Selection, group: Group) -> Selection:
    return select_blocks(sel, group.block_ids)


def deselect_group(sel: Selection, group: Group) -> Selection:
    return deselect_blocks(sel, group.block_ids)


def set_view(sel: Selection, view: GroupView) -> Selection:
    """Changes only the active view: block_ids stay byte-identical."""
    return sel.model_copy(update={"active_view": view})


def set_split(sel: Selection, split: ArticleSplit) -> Selection:
    return sel.model_copy(update={"article_split": split})


def selectable_ids(groups: Mapping[str, GroupsFile]) -> set[str]:
    return {b for gf in groups.values() for g in gf.structure for b in g.block_ids}


def normalize_to(sel: Selection, selectable: Collection[str]) -> tuple[Selection, list[str]]:
    ok = set(selectable)
    keep = [b for b in sel.block_ids if b in ok]
    dropped = [b for b in sel.block_ids if b not in ok]
    if not dropped:
        return sel, []
    return _with(sel, block_ids=keep), dropped


def normalize(sel: Selection, blocks_by_id: Mapping[str, Block]) -> tuple[Selection, list[str]]:
    """Drop unknown ids (e.g. a removed document) and header/footer ids; report them."""
    return normalize_to(sel, {i for i, b in blocks_by_id.items() if b.type not in HF_TYPES})


def load_groups(paths: ProjectPaths) -> dict[str, GroupsFile]:
    out: dict[str, GroupsFile] = {}
    for slug in paths.list_slugs():
        p = paths.doc(slug).groups
        if p.is_file():
            out[slug] = read_json(p, GroupsFile)
    return out


def default_selection(
    paths: ProjectPaths, groups: Mapping[str, GroupsFile] | None = None
) -> Selection:
    """Every selectable block of every grouped document."""
    groups = load_groups(paths) if groups is None else groups
    cfg = paths.load_config()
    return Selection(
        block_ids=sorted(selectable_ids(groups)),
        article_split=cfg.article_split,
        active_view=GroupView.topic,
    )


def load_selection(paths: ProjectPaths) -> tuple[Selection, list[str]]:
    """The saved selection (normalized), or the default when none was saved yet."""
    groups = load_groups(paths)
    if not paths.selection.is_file():
        return default_selection(paths, groups), []
    return normalize_to(read_json(paths.selection, Selection), selectable_ids(groups))


def save_selection(
    paths: ProjectPaths, sel: Selection, groups: Mapping[str, GroupsFile] | None = None
) -> tuple[Selection, list[str]]:
    groups = load_groups(paths) if groups is None else groups
    sel, dropped = normalize_to(sel, selectable_ids(groups))
    write_json(paths.selection, sel)
    return sel, dropped


def scope_summary(
    sel: Selection,
    groups: Mapping[str, GroupsFile],
    blocks: Mapping[str, Sequence[Block]],
    *,
    threshold: float,
) -> ScopeSummary:
    """Pre-cleanup estimate of what the selection will become. `blocks` come from
    load_scored_blocks, so `status` follows the threshold slider."""
    chosen, _ = normalize_to(sel, selectable_ids(groups))
    s = set(chosen.block_ids)
    docs = 0
    per_topic = 0
    figures = 0
    pages: set[tuple[str, int]] = set()
    queued = 0
    numeric = 0
    for slug, gf in groups.items():
        n_topics = sum(1 for t in gf.topics if s.intersection(t.block_ids))
        picked = [b for b in blocks.get(slug, ()) if b.id in s]
        if not picked:
            continue
        docs += 1
        per_topic += n_topics
        for b in picked:
            figures += b.type == BlockType.figure
            pages.add((slug, b.page))
            if b.status == BlockStatus.queued:
                queued += 1
                numeric += b.has_numeric_spec
    articles = per_topic if chosen.article_split == ArticleSplit.per_topic else docs
    return ScopeSummary(
        docs=docs,
        articles_per_topic=per_topic,
        articles_per_document=docs,
        articles=articles,
        blocks=len(s),
        figures=figures,
        pages=len(pages),
        review_load=ReviewLoad(queued=queued, numeric_queued=numeric, threshold=threshold),
    )
