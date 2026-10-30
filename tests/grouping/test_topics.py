"""Topic view (design tests 2 [topic half], 11-19)."""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

import numpy as np
import pytest

from manuallabor import ids
from manuallabor.contracts import Task
from manuallabor.contracts.enums import BlockType, GroupView, TitleSource, UnassignedReason
from manuallabor.grouping.cluster import center, cluster, cohesion
from manuallabor.grouping.label import (
    StragglerItem,
    fallback_name,
    name_topic,
    review_stragglers,
)
from manuallabor.grouping.mock_replies import mock_grouping_reply
from manuallabor.grouping.pipeline import group_document
from manuallabor.grouping.structure import build_structure, page_ranges
from manuallabor.grouping.summary import bound_captions
from manuallabor.grouping.topics import _bind, _place_stragglers
from manuallabor.grouping.types import Assembly, GroupStats, default_params
from manuallabor.providers import ListSink, MockProvider
from tests.grouping.conftest import (
    SLUG,
    Grouped,
    doc_of,
    gt_blocks,
    gt_document,
    heading,
    mk,
    provider_set,
)

PARAMS = default_params()


def test_partition_topic(grouped: Grouped, stem: str) -> None:
    gf, blocks = grouped.gf(stem), grouped.blocks(stem)
    hf = {b.id for b in blocks if b.type in (BlockType.header, BlockType.footer)}
    entries = [
        u for u in gf.unassigned if u.view == GroupView.topic and u.reason.value == "header_footer"
    ]
    assert {u.block_id for u in entries} == hf
    seen = [b for t in gf.topics for b in t.block_ids] + [u.block_id for u in entries]
    assert sorted(seen) == sorted(b.id for b in blocks) and len(seen) == len(set(seen))
    t000 = gf.topics[0]
    assert t000.is_unassigned and t000.id == f"g-{stem}-t000" and not (set(t000.block_ids) & hf)


def test_topics_mock_invariants(grouped: Grouped, stem: str) -> None:
    gf, blocks = grouped.gf(stem), grouped.blocks(stem)
    by_id = {b.id: b for b in blocks}
    section_of = {b: g.id for g in gf.structure for b in g.block_ids}
    assert gf.topic_status == "ok" and gf.embedding_dim == 256
    topics = [t for t in gf.topics if not t.is_unassigned]
    assert topics, "every fixture yields at least one topic"
    assert len({t.slug for t in gf.topics}) == len(gf.topics)
    for t in topics:
        assert t.block_count >= 2 and t.block_ids
        assert t.cohesion is not None and 0.0 <= t.cohesion <= 1.0
        assert t.section_ids == sorted({section_of[b] for b in t.block_ids})
        assert t.page_ranges == page_ranges([by_id[b].page for b in t.block_ids])
        assert t.figure_count == sum(by_id[b].type == BlockType.figure for b in t.block_ids)
        assert gf.title_sources[t.id] in (TitleSource.llm, TitleSource.fallback)
    assert sum(1 for g in gf.topics if g.is_unassigned) == 1


# ---------------------------------------------------------------------------------------------
# clustering core


def _vec(group: int, i: int, dim: int = 8, eps: float = 0.05) -> list[float]:
    v = [eps * math.sin(7 * i + 3 * j + group) for j in range(dim)]
    v[group] += 1.0
    return v


def _norm(rows: list[list[float]]) -> np.ndarray:
    m = np.asarray(rows, dtype=np.float64)
    return np.asarray(m / np.linalg.norm(m, axis=1)[:, None])


def _ids(n: int) -> list[str]:
    return [ids.block_id(SLUG, 1 + i // 50, 1 + i % 50) for i in range(n)]


def test_clustering_core_three_groups_two_outliers() -> None:
    rows = [_vec(g, i) for g in range(3) for i in range(5)]
    rows += [[0.0] * 5 + [1.0, 0.0, 0.0], [0.0] * 6 + [1.0, 0.0]]
    block_ids = _ids(len(rows))
    c = center(_norm(rows))
    clusters = cluster(c, block_ids, PARAMS)
    assert clusters == [list(range(0, 5)), list(range(5, 10)), list(range(10, 15))]
    # permuting the input rows (and their ids) does not change the clusters
    perm = list(reversed(range(len(rows))))
    pc = cluster(c[perm], [block_ids[i] for i in perm], PARAMS)
    mapped = sorted(sorted(block_ids[perm[i]] for i in m) for m in pc)
    assert mapped == sorted(sorted(block_ids[i] for i in m) for m in clusters)
    for m in clusters:
        assert 0.0 < cohesion(c, m) <= 1.0


@pytest.mark.parametrize("n", [0, 1, 2])
def test_clustering_tiny_inputs_do_not_crash(n: int) -> None:
    rows = [_vec(0, i) for i in range(n)]
    c = center(_norm(rows)) if rows else np.zeros((0, 0))
    out = cluster(c, _ids(n), PARAMS)
    assert out == ([] if n == 0 else [list(range(n))])


def test_small_doc_is_one_cluster() -> None:
    orth = np.eye(5)
    assert cluster(center(orth), _ids(5), PARAMS) == [[0, 1, 2, 3, 4]]


def test_three_separated_groups_above_small_doc() -> None:
    rows = []
    for g, size in enumerate([5, 4, 4]):
        for i in range(size):
            v = np.zeros(8)
            v[g] = 1.0
            v[3 + (g * 4 + i) % 5] += 0.05 * (1 + i)  # distinct distances, no ties
            rows.append(v)
    c = center(np.array(rows))
    assert cluster(c, _ids(13), PARAMS) == [[0, 1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]


def test_all_equal_distances_still_partition() -> None:
    """13 orthogonal rows: every pairwise distance is identical, so the dendrogram is decided by
    tie-breaking inside scipy's linkage, which differs between platforms (macOS gives one cluster,
    Linux two). The contract is a partition that is deterministic on one machine, not a particular
    shape (design 04 section 3.3)."""
    c = center(np.eye(13))
    out = cluster(c, _ids(13), PARAMS)
    assert cluster(c, _ids(13), PARAMS) == out
    assert sorted(i for m in out for i in m) == list(range(13))
    assert all(len(m) >= PARAMS.min_topic_blocks for m in out)


def test_size_cap_and_cannot_link() -> None:
    n = 130
    rows = [_vec(i % 2, i, eps=1e-3) for i in range(n)]
    c = center(_norm(rows))
    block_ids = _ids(n)
    clusters = cluster(c, block_ids, PARAMS)
    assert clusters and all(len(m) <= PARAMS.max_topic_blocks for m in clusters)
    members = [i for m in clusters for i in m]
    assert len(members) == len(set(members))
    # a do-not-merge pair that would otherwise share a cluster ends up apart
    rows = [_vec(0, i, eps=1e-3) for i in range(20)] + [_vec(1, i, eps=1e-3) for i in range(20)]
    c = center(_norm(rows))
    block_ids = _ids(len(rows))
    base = cluster(c, block_ids, PARAMS)
    pair = next(m for m in base if len(m) >= 4)[:: len(next(m for m in base if len(m) >= 4)) - 1]
    a, b = pair[0], pair[-1]
    split = cluster(c, block_ids, PARAMS, [(block_ids[a], block_ids[b])])
    assert not any(a in m and b in m for m in split)
    assert any(a in m for m in base) and any(a in m and b in m for m in base)


# ---------------------------------------------------------------------------------------------
# stragglers


def _straggler_setup(sims: list[float]) -> tuple[np.ndarray, list[str], np.ndarray]:
    rows = [[s, math.sqrt(1 - s * s), 0.0] for s in sims]
    return np.asarray(rows), _ids(len(sims)), np.asarray([[1.0, 0.0, 0.0]])


def test_straggler_threshold_rule_and_llm_skipped_without_candidates() -> None:
    c, block_ids, cents = _straggler_setup([0.31, 0.29, 0.10])
    summaries = {b: f"s\n{b}" for b in block_ids}
    sink = ListSink()
    seen_batches: list[Any] = []

    def spy(messages):  # type: ignore[no-untyped-def]
        seen_batches.append(json.loads(messages[1].content[7:-8]))
        return mock_grouping_reply(messages)

    chat = MockProvider(sink=sink, responses={Task.grouping: spy})
    off = PARAMS.model_copy(update={"llm_stragglers": False})
    d = _place_stragglers(
        c, block_ids, summaries, set(), cents, ["c01"], {"c01": "T"}, chat, off, [], GroupStats()
    )
    assert [(x.topic_key, x.by) for x in d] == [
        ("c01", "centroid"),
        (None, "centroid"),
        (None, "centroid"),
    ]
    assert d[1].similarity == pytest.approx(0.29) and d[2].similarity == pytest.approx(0.10)
    assert sink == []
    _place_stragglers(
        c, block_ids, summaries, set(), cents, ["c01"], {"c01": "T"}, chat, PARAMS, [], GroupStats()
    )
    assert len(seen_batches) == 1
    assert [b["block_id"] for b in seen_batches[0]["blocks"]] == block_ids[:2]


def _items() -> list[StragglerItem]:
    a, b = _ids(2)
    return [StragglerItem(a, "sa", ("c01", "c02")), StragglerItem(b, "sb", ("c01",))]


@pytest.mark.parametrize(
    "case", ["unknown_topic", "missing_block", "extra_block", "duplicate_block", "not_a_candidate"]
)
def test_straggler_llm_invalid_answers_retry_once_then_default(case: str) -> None:
    a, b = _ids(2)
    replies = {
        "unknown_topic": [(a, "c99"), (b, "unassigned")],
        "missing_block": [(a, "c01")],
        "extra_block": [(a, "c01"), (b, "c01"), ("b-doc-p009-99", "c01")],
        "duplicate_block": [(a, "c01"), (a, "c02"), (b, "c01")],
        "not_a_candidate": [(a, "c01"), (b, "c02")],
    }[case]
    text = json.dumps({"assignments": [{"block_id": x, "topic": t} for x, t in replies]})
    sink = ListSink()
    chat = MockProvider(sink=sink, responses={Task.grouping: text})
    assert review_stragglers(chat, [("c01", "A"), ("c02", "B")], _items()) is None
    assert len(sink) == 2 and sink[0].input_hash != sink[1].input_hash


def test_straggler_llm_valid_choice_is_applied() -> None:
    a, b = _ids(2)
    text = json.dumps(
        {"assignments": [{"block_id": a, "topic": "c02"}, {"block_id": b, "topic": "unassigned"}]}
    )
    sink = ListSink()
    chat = MockProvider(sink=sink, responses={Task.grouping: text})
    got = review_stragglers(chat, [("c01", "A"), ("c02", "B")], _items())
    assert got == {a: "c02", b: "unassigned"} and len(sink) == 1
    # through the placement code the choice is recorded as by="llm", even against the default
    c, block_ids, _ = _straggler_setup([0.9, 0.5])
    cents = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    picks = zip(block_ids, ["c02", "c01"], strict=True)
    text = json.dumps({"assignments": [{"block_id": x, "topic": t} for x, t in picks]})
    chat = MockProvider(sink=ListSink(), responses={Task.grouping: text})
    d = _place_stragglers(
        c, block_ids, {x: "s" for x in block_ids}, set(), cents, ["c01", "c02"],
        {"c01": "A", "c02": "B"}, chat, PARAMS, [], GroupStats(),
    )  # fmt: skip
    assert [(x.topic_key, x.by) for x in d] == [("c02", "llm"), ("c01", "llm")]


# ---------------------------------------------------------------------------------------------
# naming


BAD_NAMES = {
    "not_json": "this is not json",
    "title_81": json.dumps({"title": "x" * 81, "slug": "x"}),
    "slug_path": json.dumps({"title": "T", "slug": "../x"}),
    "slug_upper": json.dumps({"title": "T", "slug": "Unassigned"}),
    "slug_reserved": json.dumps({"title": "T", "slug": "unassigned"}),
    "slug_front": json.dumps({"title": "T", "slug": "front-matter"}),
    "title_blank": json.dumps({"title": "   ", "slug": "t"}),
    "title_control": json.dumps({"title": "a\u0000b", "slug": "t"}),
}


@pytest.mark.parametrize("case", sorted(BAD_NAMES))
def test_naming_validation_retries_once_then_falls_back(case: str) -> None:
    sink = ListSink()
    chat = MockProvider(sink=sink, responses={Task.grouping: BAD_NAMES[case]})
    named = name_topic(chat, ["2.1 Belt Inspection", "Other"], ["s1"], number=3)
    assert (named.title, named.slug, named.source) == (
        "Belt Inspection",
        "belt-inspection",
        TitleSource.fallback,
    )
    assert len(sink) == 2 and sink[0].input_hash != sink[1].input_hash


def test_naming_fallback_without_headings_and_valid_reply() -> None:
    assert fallback_name([], 7).title == "Topic 07" and fallback_name([], 7).slug == "topic-07"
    good = json.dumps({"title": "Drive belts", "slug": "drive-belts"})
    sink = ListSink()
    named = name_topic(MockProvider(sink=sink, responses={Task.grouping: good}), [], [], number=1)
    assert (named.title, named.source) == ("Drive belts", TitleSource.llm) and len(sink) == 1


def test_duplicate_slugs_are_made_unique_without_retries() -> None:
    blocks = gt_blocks("clean")
    sink = ListSink()
    reply = json.dumps({"title": "Belts", "slug": "belts"})
    ps = provider_set(sink, grouping=reply)
    off = default_params().model_copy(update={"llm_stragglers": False})
    gf = group_document(gt_document("clean", blocks), blocks, ps, params=off)
    topics = [t for t in gf.topics if not t.is_unassigned]
    assert len(topics) >= 3
    # design 04 section 3.4.1: the first keeps the name; later duplicates get a disambiguator
    # (section, page range or part) in the title, and the slug is made from the shown title.
    slugs = [t.slug for t in topics]
    assert slugs[0] == "belts" and len(set(slugs)) == len(slugs)
    assert all(sl.startswith("belts-") for sl in slugs[1:])
    titles = [t.title.lower() for t in topics]
    assert len(set(titles)) == len(titles)
    assert all("(" in t.title for t in topics[1:])
    chat = [e for e in sink if e.task == Task.grouping]
    assert chat and all(e.ok for e in chat) and len(chat) >= len(topics)
    assert len({e.input_hash for e in chat}) == len(chat)


# ---------------------------------------------------------------------------------------------
# caption and heading binding


def test_caption_follows_figure_and_heading_follows_section() -> None:
    blocks = [
        heading(1, 1, "1. A", section_number="1", heading_level=1),
        mk(1, 2, "Alpha."),
        mk(1, 3, "Beta."),
        mk(1, 4, "Gamma."),
        mk(1, 5, "", BlockType.figure),
        mk(1, 6, "Figure 1. Drive belt", BlockType.caption),
    ]
    st = build_structure(doc_of(blocks), blocks)
    caps = bound_captions(blocks)
    assert caps == {blocks[4].id: blocks[5].id}
    keys: dict[str, str | None] = {
        blocks[0].id: "c02",
        blocks[1].id: "c01",
        blocks[2].id: "c01",
        blocks[3].id: "c02",
        blocks[4].id: "c01",
        blocks[5].id: "c02",
    }
    asm = Assembly(placed=dict(keys), reasons={}, titles={}, slugs={}, sources={})
    _bind(asm, caps, st)
    assert asm.placed[blocks[5].id] == "c01"  # caption joined its figure
    assert asm.placed[blocks[0].id] == "c01"  # heading joined the plurality of its section


def test_figure_in_t000_pulls_its_caption_along() -> None:
    blocks = [
        heading(1, 1, "1. A", section_number="1", heading_level=1),
        mk(1, 2, "", BlockType.figure),
        mk(1, 3, "Figure 1. Belt", BlockType.caption),
    ]
    st = build_structure(doc_of(blocks), blocks)
    asm = Assembly(
        placed={blocks[0].id: None, blocks[1].id: None, blocks[2].id: "c01"},
        reasons={blocks[1].id: UnassignedReason.low_similarity},
        titles={}, slugs={}, sources={},
    )  # fmt: skip
    _bind(asm, bound_captions(blocks), st)
    assert asm.placed[blocks[2].id] is None
    assert asm.reasons[blocks[2].id] == UnassignedReason.low_similarity


def test_topic_counts_agree_with_unassigned_reasons(grouped: Grouped) -> None:
    gf = grouped.gf("twocol")
    reasons = Counter(u.reason.value for u in gf.unassigned if u.view == GroupView.topic)
    assert reasons["header_footer"] > 0
    assert gf.topics[0].block_count == sum(v for k, v in reasons.items() if k != "header_footer")
