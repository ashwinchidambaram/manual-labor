"""Fix-pass tests for module 4: final-assignment constraints, size cap, subtree select,
embedding validation, limits, corrupt state files, record nits."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from manuallabor import ids
from manuallabor.contracts import Task
from manuallabor.contracts.enums import UnassignedReason
from manuallabor.contracts.group import GroupOverride
from manuallabor.contracts.io import write_json
from manuallabor.grouping import topics as topics_mod
from manuallabor.grouping.cluster import center, cluster
from manuallabor.grouping.embed import embed_blocks
from manuallabor.grouping.learning import LearnedGrouping
from manuallabor.grouping.pipeline import check_partition, group_document
from manuallabor.grouping.types import GroupingError, TopicFailure, default_params
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider
from manuallabor.providers.mock import RawEmbed
from tests.grouping.conftest import Grouped, doc_of, mk, provider_set

Collect = Callable[..., tuple[list[str], list[dict[str, Any]]]]


def _ps() -> Any:
    return provider_set(ListSink())


# -- 1. do-not-merge on the final assignment ---------------------------------------------------


def test_do_not_merge_pairs_never_share_a_topic_on_clean(grouped: Grouped) -> None:
    blocks, doc = grouped.blocks("clean"), grouped.scored.doc("clean")
    base = group_document(doc, blocks, _ps())
    total = 0
    for t in base.topics:
        if t.is_unassigned or t.block_count < 4:
            continue
        for pair in (
            (t.block_ids[0], t.block_ids[-1]),
            (t.block_ids[1], t.block_ids[-1]),
            (t.block_ids[1], t.block_ids[2]),
        ):
            total += 1
            learned = LearnedGrouping(snapshot="s", do_not_merge=[pair])
            gf = group_document(doc, blocks, _ps(), learned=learned)
            tof = {b: g.id for g in gf.topics for b in g.block_ids}
            same = tof[pair[0]] == tof[pair[1]] and not gf.topics[0].block_ids.count(pair[0])
            assert not same, pair
            assert check_partition(blocks, gf) == []
    assert total >= 30


# -- 2. size cap after stragglers --------------------------------------------------------------


def test_identical_blocks_never_exceed_the_topic_cap() -> None:
    blocks = [
        mk(1 + i // 50, 1 + i % 50, "Check the drive belt tension and adjust.") for i in range(200)
    ]
    gf = group_document(doc_of(blocks), blocks, _ps())
    assert check_partition(blocks, gf) == []
    real = [t for t in gf.topics if not t.is_unassigned]
    assert real and max(t.block_count for t in real) <= 60
    assert sum(t.block_count for t in gf.topics) == 200 and gf.topics[0].block_count == 0


# -- 4. small doc rule -------------------------------------------------------------------------


@pytest.mark.parametrize("n", [3, 8, 11])
def test_fewer_than_twelve_candidates_form_one_topic(n: int) -> None:
    blocks = [mk(1, i + 1, f"Unique words zz{i} alpha{i} beta{i * 7}") for i in range(n)]
    gf = group_document(doc_of(blocks), blocks, _ps())
    topics = [t for t in gf.topics if not t.is_unassigned]
    assert len(topics) == 1 and topics[0].block_count == n and gf.topics[0].block_count == 0


# -- 6. embedding validation -------------------------------------------------------------------


class _Raw(MockProvider):
    def __init__(self, make: Callable[[Sequence[str]], list[list[float]]], **kw: Any) -> None:
        super().__init__(**kw)
        self._make = make

    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        return RawEmbed(self._make(texts), 1)


BAD = {
    "wrong_count": lambda t: [[1.0, 0.0]] * (len(t) - 1),
    "unequal_dims": lambda t: [[1.0, 0.0]] + [[1.0, 0.0, 0.0]] * (len(t) - 1),
    "non_finite": lambda t: [[1.0, float("nan")]] * len(t),
    "zero_norm": lambda t: [[0.0, 0.0]] * len(t),
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_bad_embeddings_fail_the_topic_view_and_write_no_topic(case: str) -> None:
    blocks = [mk(1, i + 1, f"Some words {i}") for i in range(14)]
    sink = ListSink()
    ps = provider_set(sink, embeddings=_Raw(BAD[case], sink=sink))
    gf = group_document(doc_of(blocks), blocks, ps)
    assert gf.topic_status == "failed" and gf.topic_error
    assert [t.id for t in gf.topics] == ["g-doc-t000"] and gf.embedding_dim == 0
    assert {u.reason for u in gf.unassigned if u.view.value == "topic"} == {
        UnassignedReason.topic_failed
    }
    assert check_partition(blocks, gf) == []


@pytest.mark.parametrize("case", ["unequal_dims", "non_finite", "zero_norm", "wrong_count"])
def test_embed_blocks_rejects_malformed_vectors_directly(case: str) -> None:
    class P:
        def embed(self, task: Task, texts: Sequence[str]) -> list[list[float]]:
            return BAD[case](texts)

    with pytest.raises(TopicFailure):
        embed_blocks(P(), ["a", "b", "c"], ["x", "y", "z"], prefix="", batch=8)  # type: ignore[arg-type]


# -- MAX_GROUPS, k_max -------------------------------------------------------------------------


def test_too_many_topics_raise_and_write_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(topics_mod, "MAX_GROUPS", 2)
    blocks = [
        mk(1 + i // 20, 1 + i % 20, f"{'alpha' if i < 30 else 'omega'} w{i % 3} text")
        for i in range(60)
    ]
    ps = _ps()
    with pytest.raises(GroupingError, match="exceed"):
        group_document(doc_of(blocks), blocks, ps)


def test_k_max_recut_limits_the_cluster_count() -> None:
    dim, per = 20, 3
    rows = np.zeros((dim * per, dim))
    for g in range(dim):
        for j in range(per):
            rows[g * per + j, g] = 1.0
            rows[g * per + j, (g + 1 + j) % dim] += 0.01 * (j + 1)
    rows /= np.linalg.norm(rows, axis=1)[:, None]
    c = center(rows)
    block_ids = [ids.block_id("doc", 1 + i // 50, 1 + i % 50) for i in range(dim * per)]
    free = cluster(c, block_ids, default_params().model_copy(update={"k_max_divisor": 1}))
    capped = cluster(c, block_ids, default_params())
    assert len(free) == dim
    assert len(capped) <= (dim * per) // 4 < len(free)
    assert sorted(i for m in capped for i in m) == sorted(set(i for m in capped for i in m))


# -- corrupt / invalid state files -------------------------------------------------------------


def test_corrupt_prior_groups_json_is_regenerated(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    run_and_collect(scored_copy, only="manual")
    good = scored_copy.doc("manual").groups.read_bytes()
    scored_copy.doc("manual").groups.write_text("{ not json", encoding="utf-8")
    failed, lines = run_and_collect(scored_copy, only="manual")
    assert failed == [] and lines[-1]["status"] == "done"
    assert scored_copy.doc("manual").groups.read_bytes() == good


def test_invalid_overrides_file_is_an_error_naming_the_path(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    p = scored_copy.doc("manual").group_overrides
    p.write_text(json.dumps([{"seq": 1, "kind": "move"}]), encoding="utf-8")
    failed, lines = run_and_collect(scored_copy, only="manual")
    assert failed == ["manual"] and lines[-1]["status"] == "error"
    assert str(p) in lines[-1]["detail"]
    assert not scored_copy.doc("manual").groups.exists()


def test_invalid_learning_snapshot_is_an_error_naming_the_path(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    cfg = scored_copy.load_config().model_dump(mode="json")
    cfg["learning"] = {"enabled": True}
    write_json(scored_copy.config, type(scored_copy.load_config()).model_validate(cfg))
    scored_copy.learned_grouping.parent.mkdir(parents=True, exist_ok=True)
    scored_copy.learned_grouping.write_text('{"snapshot": 5, "do_not_merge": "x"}')
    failed, lines = run_and_collect(scored_copy, only="manual")
    assert failed == ["manual"] and lines[-1]["status"] == "error"
    assert str(scored_copy.learned_grouping) in lines[-1]["detail"]


# -- 7. nits -----------------------------------------------------------------------------------


def test_override_on_a_topic_emptied_by_earlier_overrides_is_stale(grouped: Grouped) -> None:
    blocks, doc = grouped.blocks("clean"), grouped.scored.doc("clean")
    base = group_document(doc, blocks, _ps())
    real = sorted((t for t in base.topics if not t.is_unassigned), key=lambda t: t.block_count)
    x, y = real[0], real[-1]
    ov = [
        GroupOverride(seq=i + 1, kind="move", block_id=b, to_topic_slug=y.slug)
        for i, b in enumerate(x.block_ids)
    ]
    ov.append(GroupOverride(seq=99, kind="rename", topic_slug=x.slug, title="Gone"))
    gf = group_document(doc, blocks, _ps(), overrides=ov)
    assert x.slug not in {t.slug for t in gf.topics}
    assert gf.overrides_stale == [len(ov) - 1]
    assert gf.overrides_applied == len(ov) - 1


def test_member_dropped_from_a_dissolved_topic_gets_a_straggler_record(grouped: Grouped) -> None:
    blocks, doc = grouped.blocks("clean"), grouped.scored.doc("clean")
    base = group_document(doc, blocks, _ps())
    in_straggler = {r.block_id for r in base.stragglers}
    y = max((t for t in base.topics if not t.is_unassigned), key=lambda t: t.block_count)
    x = next(
        t
        for t in base.topics
        if not t.is_unassigned
        and t is not y
        and sum(b not in in_straggler for b in t.block_ids) >= 2
    )
    keep = next(b for b in x.block_ids if b not in in_straggler)
    ov = [
        GroupOverride(seq=i + 1, kind="move", block_id=b, to_topic_slug=y.slug)
        for i, b in enumerate(b for b in x.block_ids if b != keep)
    ]
    gf = group_document(doc, blocks, _ps(), overrides=ov)
    assert keep in gf.topics[0].block_ids
    rec = {r.block_id: r for r in gf.stragglers}
    assert keep in rec and rec[keep].topic_id is None and rec[keep].by == "centroid"


def test_straggler_moved_by_binding_records_similarity_to_its_final_topic() -> None:
    from manuallabor.contracts.group import StragglerRecord  # noqa: F401
    from manuallabor.grouping.types import Assembly, StragglerDecision

    c = np.asarray([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])
    bids = [ids.block_id("doc", 1, i + 1) for i in range(3)]
    asm = Assembly(
        placed={bids[0]: "c01", bids[1]: "c02", bids[2]: "c02"},
        reasons={}, titles={"c01": "A", "c02": "B"}, slugs={}, sources={},
    )  # fmt: skip
    dec = [StragglerDecision(bids[2], "c01", 0.6, "centroid")]
    recs = topics_mod._straggler_records(
        dec, asm, {"c01": "g-doc-t001", "c02": "g-doc-t002"},
        c, {b: i for i, b in enumerate(bids)}, set(), {}, {},
    )  # fmt: skip
    assert len(recs) == 1 and recs[0].topic_id == "g-doc-t002"
    assert recs[0].similarity == pytest.approx(0.9 / float(np.hypot(0.3, 0.9)), abs=1e-6)
