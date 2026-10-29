"""Selection, normalization, review load, scope summary (design tests 23-26)."""

from __future__ import annotations

from pathlib import Path

from manuallabor.contracts.enums import ArticleSplit, BlockStatus, BlockType, GroupView
from manuallabor.contracts.io import dump_json
from manuallabor.contracts.selection import Selection
from manuallabor.grouping.selection import (
    default_selection,
    deselect_group,
    load_selection,
    normalize,
    save_selection,
    scope_summary,
    select_blocks,
    select_group,
    selectable_ids,
    set_split,
    set_view,
)
from manuallabor.scoring.queue import assign_status
from tests.grouping.conftest import Grouped, mini_project


def test_selection_survives_view_toggle_and_round_trips(grouped: Grouped, tmp_path: Path) -> None:
    paths = mini_project(grouped, tmp_path / "mini")
    sel, dropped = load_selection(paths)  # no file yet: the default
    assert dropped == [] and not paths.selection.exists()
    assert set(sel.block_ids) == selectable_ids(grouped.all_groups())
    gf = grouped.gf("clean")
    sel = deselect_group(sel, gf.topics[1])
    before = dump_json(sel)
    toggled = set_view(set_view(sel, GroupView.structure), GroupView.topic)
    assert toggled.block_ids == sel.block_ids and dump_json(toggled) == before
    assert set_view(sel, GroupView.structure).block_ids == sel.block_ids
    saved, _ = save_selection(paths, set_split(sel, ArticleSplit.per_document))
    loaded, _ = load_selection(paths)
    assert loaded == saved and loaded.article_split == ArticleSplit.per_document
    assert select_group(loaded, gf.topics[1]).block_ids != loaded.block_ids


def test_normalize_drops_header_footer_and_unknown_documents(grouped: Grouped) -> None:
    blocks = grouped.blocks("clean")
    hf = next(b.id for b in blocks if b.type == BlockType.footer)
    body = next(b.id for b in blocks if b.type == BlockType.paragraph)
    sel = Selection(block_ids=[hf, body, "b-removed-doc-p001-01"])
    out, dropped = normalize(sel, {b.id: b for b in blocks})
    assert out.block_ids == [body] and sorted(dropped) == sorted([hf, "b-removed-doc-p001-01"])


def test_review_load_matches_load_scored_blocks_and_follows_threshold(grouped: Grouped) -> None:
    groups = {"clean": grouped.gf("clean")}
    blocks = {"clean": grouped.blocks("clean")}
    everything = default_selection(grouped.paths, groups)
    s = scope_summary(everything, groups, blocks, threshold=0.85)
    queued = [
        b
        for b in blocks["clean"]
        if b.status == BlockStatus.queued and b.id in set(everything.block_ids)
    ]
    assert s.review_load.queued == len(queued) > 0
    assert s.review_load.numeric_queued == sum(b.has_numeric_spec for b in queued)
    assert s.review_load.numeric_queued <= s.review_load.queued
    one = select_group(Selection(block_ids=[]), groups["clean"].topics[1])
    s1 = scope_summary(one, groups, blocks, threshold=0.85)
    assert s1.review_load.queued == sum(
        1 for b in blocks["clean"] if b.id in set(one.block_ids) and b.status == BlockStatus.queued
    )
    strict = [
        b.model_copy(update={"status": assign_status(b.confidence, b.has_numeric_spec, 1.0)})
        for b in blocks["clean"]
    ]
    s2 = scope_summary(everything, groups, {"clean": strict}, threshold=1.0)
    assert s2.review_load.queued >= s.review_load.queued and s2.review_load.threshold == 1.0


def test_scope_summary_counts(grouped: Grouped) -> None:
    groups = {k: grouped.gf(k) for k in ("clean", "figures")}
    blocks = {k: grouped.blocks(k) for k in groups}
    clean, figures = groups["clean"], groups["figures"]
    topic_a, topic_b = clean.topics[1], figures.topics[1]
    sel = select_blocks(Selection(block_ids=[]), [*topic_a.block_ids, *topic_b.block_ids])
    s = scope_summary(sel, groups, blocks, threshold=0.85)
    chosen = set(sel.block_ids)
    picked = [b for k in blocks for b in blocks[k] if b.id in chosen]
    assert s.docs == 2 and s.articles_per_document == 2 and s.blocks == len(chosen)
    assert s.figures == sum(b.type == BlockType.figure for b in picked)
    assert s.pages == len({(b.doc_id, b.page) for b in picked})
    expect_topics = sum(1 for gf in groups.values() for t in gf.topics if chosen & set(t.block_ids))
    assert s.articles_per_topic == expect_topics >= 2
    assert s.articles == s.articles_per_topic  # per_topic is the default split
    s_doc = scope_summary(set_split(sel, ArticleSplit.per_document), groups, blocks, threshold=0.85)
    assert s_doc.articles == 2
    # one selected block in t000 still counts as an article (`<doc>--unassigned`)
    t000 = clean.topics[0]
    if t000.block_ids:
        only = select_blocks(Selection(block_ids=[]), t000.block_ids[:1])
        assert scope_summary(only, groups, blocks, threshold=0.85).articles_per_topic == 1
