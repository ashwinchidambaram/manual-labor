"""Structure view (design tests 1 [structure half], 4-10)."""

from __future__ import annotations

import pytest

from manuallabor.contracts.enums import BlockType, GroupView, TitleSource, UnassignedReason
from manuallabor.grouping.structure import build_structure, page_ranges
from tests.grouping.conftest import (
    SLUG,
    Grouped,
    doc_of,
    gt_headings,
    gt_sections,
    heading,
    mk,
)


def test_partition_structure(grouped: Grouped, stem: str) -> None:
    gf, blocks = grouped.gf(stem), grouped.blocks(stem)
    seen: list[str] = [b for g in gf.structure for b in g.block_ids]
    hf_ids = {b.id for b in blocks if b.type in (BlockType.header, BlockType.footer)}
    entries = [u for u in gf.unassigned if u.view == GroupView.structure]
    assert {u.block_id for u in entries} == hf_ids
    assert all(u.reason == UnassignedReason.header_footer for u in entries)
    everything = [*seen, *(u.block_id for u in entries)]
    assert sorted(everything) == sorted(b.id for b in blocks)
    assert len(everything) == len(set(everything))


def _nodes(gf):  # type: ignore[no-untyped-def]
    return [g for g in gf.structure if gf.title_sources[g.id] == TitleSource.heading]


@pytest.mark.parametrize("name", ["clean", "twocol", "tables", "figures"])
def test_structure_matches_ground_truth(grouped: Grouped, name: str) -> None:
    gf = grouped.gf(name)
    nodes = _nodes(gf)
    heads = gt_headings(name)
    assert [g.section_number for g in nodes] == [h["section_number"] for h in heads]
    if name == "clean":
        assert nodes[0].title == "Acme X200 Service Manual" and nodes[0].section_number is None
    by_id = {g.id: g for g in gf.structure}
    for g in nodes:
        num = g.section_number
        if num and "." in num:
            assert g.parent_id is not None
            assert by_id[g.parent_id].section_number == num.rsplit(".", 1)[0]
            assert g.level == 2
        elif num:
            assert g.parent_id is None and g.level == 1
    for (_, pages), g in zip(gt_sections(name), nodes, strict=True):
        assert g.page_ranges == page_ranges(pages)


def test_structure_scanned_matches_clean(grouped: Grouped) -> None:
    scanned = [g.section_number for g in _nodes(grouped.gf("scanned"))]
    clean = [g.section_number for g in _nodes(grouped.gf("clean"))]
    assert scanned == clean and len(scanned) == 18


def test_docx_virtual_pages(grouped: Grouped) -> None:
    gf = grouped.gf("manual")
    s = gf.structure
    assert [g.id for g in s] == ["g-manual-s001", "g-manual-s002", "g-manual-s003"]
    assert [g.title for g in s] == ["1. Overview", "1.1 Required Items", "2. Maintenance"]
    assert [[(r.start, r.end) for r in g.page_ranges] for g in s] == [[(1, 1)], [(1, 1)], [(2, 2)]]
    assert s[1].parent_id == s[0].id and s[0].parent_id is None and s[2].parent_id is None
    assert [g.level for g in s] == [1, 2, 1]


def test_front_matter() -> None:
    blocks = [
        mk(1, 1, "Preface text."),
        mk(1, 2, "More preface."),
        heading(1, 3, "1. Intro", section_number="1", heading_level=1),
        mk(1, 4, "Body."),
    ]
    res = build_structure(doc_of(blocks), blocks)
    g = res.groups[0]
    assert (g.id, g.title, g.slug, g.level, g.parent_id) == (
        f"g-{SLUG}-s001",
        "Front matter",
        "front-matter",
        1,
        None,
    )
    assert g.block_ids == [blocks[0].id, blocks[1].id]
    assert res.groups[1].title == "1. Intro" and res.groups[1].block_count == 2
    starts_with_heading = [blocks[2], blocks[3]]
    assert [
        x.title for x in build_structure(doc_of(starts_with_heading), starts_with_heading).groups
    ] == ["1. Intro"]


def test_repair_number_beats_level_jumps_and_missing_level() -> None:
    blocks = [
        heading(1, 1, "1. A", section_number="1", heading_level=1),
        heading(1, 2, "1.1 B", section_number="1.1", heading_level=1),  # number wins: level 2
        heading(2, 1, "Top", heading_level=1),
        heading(2, 2, "Deep", heading_level=3),  # jump 1 -> 3
        heading(3, 1, "No level"),  # inherits the previous node's level
    ]
    g = {x.title: x for x in build_structure(doc_of(blocks), blocks).groups}
    assert g["1.1 B"].level == 2 and g["1.1 B"].parent_id == g["1. A"].id
    assert g["Deep"].level == 2 and g["Deep"].parent_id == g["Top"].id
    assert g["No level"].parent_id == g["Top"].id and g["No level"].level == 2


def test_demoted_headings_stay_in_the_enclosing_group() -> None:
    table = mk(1, 3, "a | b", BlockType.table, bbox=[0, 200, 200, 300])
    blocks = [
        heading(1, 1, "1. A", section_number="1", heading_level=1),
        mk(1, 2, "Text."),
        table,
        heading(1, 4, "Cell label", heading_level=2, bbox=[10, 210, 100, 230]),  # D2
        heading(1, 5, "   ", heading_level=2),  # D1
        heading(1, 6, "Figure 3. Drive belt routing", heading_level=2, bbox=[0, 500, 100, 510]),
    ]
    res = build_structure(doc_of(blocks), blocks)
    assert len(res.groups) == 1
    assert res.groups[0].block_ids == [b.id for b in blocks]
    assert res.title_sources[res.groups[0].id] == TitleSource.heading


def test_no_headings_uses_page_windows() -> None:
    blocks = [mk(p, 1, f"Page {p} text.") for p in range(1, 26)]
    res = build_structure(doc_of(blocks), blocks)
    assert [g.slug for g in res.groups] == ["pages-001-010", "pages-011-020", "pages-021-025"]
    assert [g.title for g in res.groups] == [
        "Pages 1–10",
        "Pages 11–20",
        "Pages 21–25",
    ]
    assert [g.block_count for g in res.groups] == [10, 10, 5]


def test_header_footer_are_never_in_groups() -> None:
    blocks = [
        mk(1, 1, "Running header", BlockType.header),
        heading(1, 2, "1. A", section_number="1", heading_level=1),
        mk(1, 3, "Page 1", BlockType.footer),
    ]
    res = build_structure(doc_of(blocks), blocks)
    assert [b for g in res.groups for b in g.block_ids] == [blocks[1].id]
    assert {u.block_id for u in res.unassigned} == {blocks[0].id, blocks[2].id}
