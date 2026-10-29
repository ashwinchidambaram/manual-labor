"""Coverage mapping between the two views (design §4). Pure and exact."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from manuallabor.contracts.enums import GroupView
from manuallabor.contracts.group import Group, GroupOverlap, GroupsFile
from manuallabor.contracts.selection import CoverageReport, GroupCoverage


def overlap(structure: Sequence[Group], topics: Sequence[Group]) -> list[GroupOverlap]:
    """For every (topic, section) pair with a non-empty intersection, its block count."""
    section_of = {b: g.id for g in structure for b in g.block_ids}
    counts: dict[tuple[str, str], int] = {}
    for t in topics:
        for b in t.block_ids:
            s = section_of.get(b)
            if s is not None:
                counts[(t.id, s)] = counts.get((t.id, s), 0) + 1
    return [
        GroupOverlap(topic_id=t, section_id=s, blocks=n) for (t, s), n in sorted(counts.items())
    ]


def _fraction(selected: int, total: int) -> float | None:
    return None if total == 0 else round(selected / total, 6) + 0.0


def coverage(selected: Collection[str], gf: GroupsFile) -> CoverageReport:
    """How much of every group of both views is selected. Ids that belong to another
    document or to a header/footer are ignored."""
    sel = frozenset(selected)
    selectable = {b for g in gf.structure for b in g.block_ids}
    own = {g.id: len(sel.intersection(g.block_ids)) for g in gf.structure}
    index = {g.id: i for i, g in enumerate(gf.structure)}
    sub_sel = dict(own)
    sub_tot = {g.id: g.block_count for g in gf.structure}
    for g in reversed(gf.structure):  # children follow their parent in preorder
        if g.parent_id is not None and g.parent_id in index:
            sub_sel[g.parent_id] += sub_sel[g.id]
            sub_tot[g.parent_id] += sub_tot[g.id]
    structure = [
        GroupCoverage(
            group_id=g.id,
            view=GroupView.structure,
            selected=own[g.id],
            total=g.block_count,
            fraction=_fraction(own[g.id], g.block_count),
            subtree_selected=sub_sel[g.id],
            subtree_total=sub_tot[g.id],
            subtree_fraction=_fraction(sub_sel[g.id], sub_tot[g.id]),
        )
        for g in gf.structure
    ]
    topics: list[GroupCoverage] = []
    for t in gf.topics:
        n = len(sel.intersection(t.block_ids))
        topics.append(
            GroupCoverage(
                group_id=t.id,
                view=GroupView.topic,
                selected=n,
                total=t.block_count,
                fraction=_fraction(n, t.block_count),
                subtree_selected=None,
                subtree_total=None,
                subtree_fraction=None,
            )
        )
    return CoverageReport(
        doc_id=gf.doc_id,
        selected=len(sel & selectable),
        selectable=len(selectable),
        structure=structure,
        topics=topics,
    )
