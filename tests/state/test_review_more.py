"""Flags, page renders, page blocks and details (the branches S4-S8 do not reach)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from manuallabor.contracts.enums import BlockStatus, BlockType, FlagCategory, FlagStatus
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp, NotFound, OutOfScope
from manuallabor.state.models import FlagIn, SelectionOp
from tests.state.helpers import Env


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def first_para(env: Env, slug: str = "clean"):  # type: ignore[no-untyped-def]
    for item in env.review.queue(None, None, slug, 500, 0).items:
        if item.type == BlockType.paragraph:
            return item
    raise AssertionError("none")


def test_flag_resolution_endpoint_semantics(env: Env) -> None:
    item = first_para(env)
    out = env.act("flag", item.block_id, flag=FlagIn(category=FlagCategory.wrong_text, note="x"))
    assert out.flag is not None and out.block_status == BlockStatus.flagged
    assert [f.id for f in env.review.flags(FlagStatus.open)] == [out.flag.id]
    assert env.review.flags(FlagStatus.resolved) == []
    done = env.review.resolve_flag(out.flag.id, "handled by hand", "r1")
    assert done.status == FlagStatus.resolved and done.resolution == "handled by hand"
    assert env.review.resolve_flag(out.flag.id, "handled by hand", "r1") == done  # replay
    with pytest.raises(InvalidOp):
        env.review.resolve_flag(out.flag.id, "again", "r2")
    with pytest.raises(NotFound):
        env.review.resolve_flag("flag-000099", "x", "r3")
    # a resolved flag returns the block to its machine status
    d = env.review.detail(item.block_id)
    assert d.block.status in (BlockStatus.queued, BlockStatus.auto_approved)
    assert [f.status for f in d.flags] == [FlagStatus.resolved]
    assert len(d.history) == 1 and d.history[0].decision.flag_id == out.flag.id


def test_flag_target_must_belong_to_the_block(env: Env) -> None:
    item = first_para(env)
    other = first_para(env, "scanned")
    with pytest.raises(InvalidOp):
        env.act(
            "flag",
            item.block_id,
            flag=FlagIn(category=FlagCategory.wrong_text, target_id=other.block_id),
        )
    with pytest.raises(InvalidOp):
        env.act("flag", item.block_id)  # no flag details


def test_figure_flag_by_figure_id_and_detail_rail(env: Env) -> None:
    block = next(b for b in env.data.raw_blocks("clean") if b.type == BlockType.figure)
    fig = block
    out = env.act(
        "flag",
        fig.id,
        flag=FlagIn(category=FlagCategory.bad_crop, target_id=block.figure_id),
    )
    assert out.flag is not None and out.flag.target_id == block.figure_id
    d = env.review.detail(fig.id)
    assert d.block.type == BlockType.figure and d.block.status == BlockStatus.flagged
    assert any(f.figure_id == block.figure_id for f in d.figures)
    assert d.article_ids and d.page.render_url is not None and d.page.source_url.endswith("/source")


def test_detail_errors_and_scope(env: Env) -> None:
    with pytest.raises(NotFound):
        env.review.detail("b-nope-p001-01")
    with pytest.raises(NotFound):
        env.review.detail("not an id")
    victim = next(b for b in env.data.selection().block_ids if b.startswith("b-clean-"))
    env.scope.apply(SelectionOp(op="deselect", block_ids=[victim], request_id="d"))
    with pytest.raises(OutOfScope):
        env.review.detail(victim)


def test_page_render_and_page_blocks(env: Env) -> None:
    p = env.review.render_page("clean", 1, 72)
    assert p.is_file() and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert p == env.paths.doc("clean").page_view(1, 72)
    assert env.review.render_page("clean", 1, 72) == p  # cached
    with pytest.raises(NotFound):
        env.review.render_page("clean", 99, 72)
    with pytest.raises(NotFound):
        env.review.render_page("nope", 1, 72)
    blocks = env.review.page_blocks("clean", 1)
    assert blocks and {"block_id", "bbox", "type", "status"} <= set(blocks[0])
    assert all(b["block_id"].startswith("b-clean-p001-") for b in blocks)
    # a DOCX has no page render
    from manuallabor.contracts.enums import DocKind
    from manuallabor.state.errors import NoPageRender

    doc = env.data.document("clean")
    env.data._cache[("document", "clean")] = (
        env.data._cache[("document", "clean")][0],
        doc.model_copy(update={"kind": DocKind.docx, "pages_without_text_layer": []}),
    )
    with pytest.raises(NoPageRender):
        env.review.render_page("clean", 1, 72)
