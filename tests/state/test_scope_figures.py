"""Scope, regroup, threshold and figure services (the A side of API tests A3, A6, A7)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.group import GroupOverride
from manuallabor.contracts.io import read_json
from manuallabor.figures.pipeline import load_bbox_overrides
from manuallabor.figures.types import FigureReport
from manuallabor.jobs.executor import run_node
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import ActionKind, RegroupIn, SelectionOp
from tests.state.helpers import Env


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def groups_of(env: Env, slug: str = "clean"):  # type: ignore[no-untyped-def]
    gf = env.data.groups(slug)
    assert gf is not None
    return gf


def test_a3_select_group_subtree_and_set_view_keep_block_ids(env: Env) -> None:
    gf = groups_of(env)
    env.scope.apply(
        SelectionOp(op="deselect", block_ids=list(env.data.selection().block_ids), request_id="a")
    )
    top = next(g for g in gf.structure if g.parent_id is None and len(gf.structure) > 1)
    own = env.scope.apply(
        SelectionOp(op="select_group", group_id=top.id, doc_id="clean", request_id="b")
    )
    sub = env.scope.apply(
        SelectionOp(
            op="select_group", group_id=top.id, doc_id="clean", subtree=True, request_id="c"
        )
    )
    assert set(own.selection.block_ids) <= set(sub.selection.block_ids)
    before = sub.selection.block_ids
    flipped = env.scope.apply(SelectionOp(op="set_view", view="structure", request_id="d"))
    assert (
        flipped.selection.block_ids == before and flipped.selection.active_view.value == "structure"
    )
    split = env.scope.apply(SelectionOp(op="set_split", split="per_document", request_id="e"))
    assert split.selection.article_split.value == "per_document"
    # coverage numbers and the summary follow the selection and agree with each other
    cov = next(c for c in split.coverage if c.doc_id == "clean")
    assert cov.selected == sum(1 for b in before if b.startswith("b-clean-"))
    assert split.summary.blocks == len(before)
    # persists across a new service instance
    env.close()
    again = Env(env.paths)
    try:
        assert again.scope.get().selection.block_ids == before
    finally:
        again.close()
    env.store = type(env.store).open(env.paths)


def test_selection_ops_validate(env: Env) -> None:
    with pytest.raises(NotFound):
        env.scope.apply(SelectionOp(op="select_group", group_id="g-clean-s999", request_id="x"))
    with pytest.raises(InvalidOp):
        env.scope.apply(SelectionOp(op="set_view", request_id="y"))
    gone = env.scope.apply(SelectionOp(op="select", block_ids=["b-nope-p001-01"], request_id="z"))
    assert "b-nope-p001-01" in gone.dropped and "b-nope-p001-01" not in gone.selection.block_ids


def test_regroup_records_override_example_and_projection(env: Env) -> None:
    gf = groups_of(env)
    topics = [t for t in gf.topics if not t.is_unassigned]
    mover = topics[0].block_ids[0]
    ov = env.scope.regroup(
        RegroupIn(
            doc_id="clean",
            kind="move",
            block_id=mover,
            to_topic_slug=topics[1].slug,
            request_id="m",
        )
    )
    assert isinstance(ov, GroupOverride) and ov.seq >= 1
    file_rows = json.loads(env.paths.doc("clean").group_overrides.read_text())
    assert file_rows == [ov.model_dump(mode="json")]
    act = [a for a in env.store.iter_actions() if a.kind == ActionKind.regroup_move][0]
    assert act.example is not None and act.example["regroup"]["to_topic"] == topics[1].slug
    assert act.learning_provenance == "baseline"
    with pytest.raises(InvalidOp):
        env.scope.regroup(
            RegroupIn(doc_id="clean", kind="rename", topic_slug=topics[0].slug, request_id="r")
        )
    with pytest.raises(NotFound):
        env.scope.regroup(
            RegroupIn(doc_id="nope", kind="rename", topic_slug="a-b", title="T", request_id="r2")
        )


def test_a6_project_threshold_changes_only_config_and_history(env: Env) -> None:
    n_dec = len(env.store.decisions())
    assert env.scope.set_project_threshold(0.9, "slider", "t1") == 0.9
    assert env.paths.load_config().threshold == 0.9
    rows = env.store.q("SELECT kind, old, new, reason FROM threshold_history")
    assert [tuple(r) for r in rows] == [("project", 0.85, 0.9, "slider")]
    assert len(env.store.decisions()) == n_dec
    with pytest.raises(InvalidOp):
        env.scope.set_project_threshold(1.5, "x", "t2")
    env.scope.set_project_threshold(0.9, "slider", "t1")  # a replay changes nothing
    assert env.store.q1("SELECT COUNT(*) FROM threshold_history")[0] == 1  # type: ignore[index]


def figure_block(env: Env):  # type: ignore[no-untyped-def]
    for b in env.data.raw_blocks("clean"):
        if b.type == BlockType.figure:
            return b
    raise AssertionError("no figure")


def test_a7_rail_attach_detach_and_bbox(env: Env) -> None:
    af = env.data.attach("clean")
    assert af is not None and af.articles
    art = af.articles[0]
    rail = env.figures.rail(art.article_id)
    assert rail and rail[0].image_url.startswith("/api/figures/FIG-")
    assert rail[0].attachment is not None and rail[0].attachment.article_id == art.article_id
    assert env.figures.image_path(rail[0].figure_id).is_file()
    fid = rail[0].figure_id
    ov = env.figures.detach(fid, art.article_id, "d1")
    assert ov.op == "detach"
    ov2 = env.figures.attach(fid, art.article_id, None, "a1")
    assert ov2.op == "attach" and ov2.seq > ov.seq
    rows = json.loads(env.paths.doc("clean").attach_overrides.read_text())
    assert [r["op"] for r in rows] == ["detach", "attach"]
    with pytest.raises(InvalidOp):
        env.figures.attach(fid, "scanned--whatever", None, "a2")  # another document
    with pytest.raises(NotFound):
        env.figures.image_path("FIG-clean-p001-99")
    # a crop override: stored, projected, and picked up by the figures stage (F2)
    blk = figure_block(env)
    assert blk.bbox is not None and blk.figure_id is not None
    x0, y0, x1, y1 = blk.bbox
    new_box = [x0 + 2.0, y0 + 2.0, x1 - 2.0, y1 - 2.0]
    env.figures.set_bbox(blk.figure_id, new_box, "bb")
    assert load_bbox_overrides(env.paths.doc("clean")) == {blk.figure_id: new_box}
    assert run_node(env.paths, "figures", only="clean", emit=lambda _o: None) == []
    rep = read_json(env.paths.doc("clean").figure_report, FigureReport)
    mine = next(f for f in rep.figures if f.figure_id == blk.figure_id)
    assert mine.reason == "human_bbox" and mine.bbox == new_box
    assert {f.figure_id for f in rep.figures} >= {blk.figure_id}  # the id never changes
    with pytest.raises(InvalidOp):
        env.figures.set_bbox(blk.figure_id, [10.0, 10.0, 5.0, 5.0], "bad")
