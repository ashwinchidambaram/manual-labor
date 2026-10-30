"""Concurrent override writes must not collide on the UNIQUE `seq` (code review F2).

API routes are sync and run in a threadpool. Each test makes two requests read their sequence
number at the same moment (a barrier inside `next_*`), which is what happens when the read sits
outside the transaction. With the read inside `Store.tx()`, the second request cannot reach it
until the first has committed: the barrier times out and both writes succeed with distinct seqs."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from manuallabor.contracts.enums import BlockType
from manuallabor.project import ProjectPaths
from manuallabor.state.models import RegroupIn
from tests.state.helpers import Env


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def _rendezvous(env: Env, name: str, parties: int = 2) -> None:
    """Make `env.store.<name>` wait (briefly) for the other request after reading its value."""
    real = getattr(env.store, name)
    barrier = threading.Barrier(parties)

    def slow(*a: Any, **kw: Any) -> Any:
        v = real(*a, **kw)
        # a timeout means the transaction serialised the requests: the other one is not here yet
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=0.5)
        return v

    setattr(env.store, name, slow)


def _both(calls: list[Callable[[], object]]) -> tuple[list[object], list[BaseException]]:
    out: list[object] = []
    errors: list[BaseException] = []

    def run(fn: Callable[[], object]) -> None:
        try:
            out.append(fn())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out, errors


def test_concurrent_regroups_get_distinct_seqs(env: Env) -> None:
    gf = env.data.groups("clean")
    assert gf is not None
    topics = [t for t in gf.topics if not t.is_unassigned]
    a, b = topics[0].block_ids[:2]
    _rendezvous(env, "next_override_seq")
    out, errors = _both(
        [
            lambda bid=bid, rid=rid: env.scope.regroup(  # type: ignore[misc]
                RegroupIn(
                    doc_id="clean",
                    kind="move",
                    block_id=bid,
                    to_topic_slug=topics[1].slug,
                    request_id=rid,
                )
            )
            for bid, rid in ((a, "m1"), (b, "m2"))
        ]
    )
    assert not errors, f"{type(errors[0]).__name__}: {errors[0]}"
    rows = env.store.overrides("group_overrides", "clean")
    assert len(rows) == 2 and len({seq for seq, _d, _b in rows}) == 2
    assert sorted(o.seq for o in out) == sorted(seq for seq, _d, _b in rows)  # type: ignore[attr-defined]


def test_concurrent_attach_overrides_get_distinct_seqs(env: Env) -> None:
    af = env.data.attach("clean")
    assert af is not None
    art = af.articles[0]
    fid = env.figures.rail(art.article_id)[0].figure_id
    _rendezvous(env, "next_override_seq")
    out, errors = _both(
        [
            lambda: env.figures.detach(fid, art.article_id, "d1"),
            lambda: env.figures.attach(fid, art.article_id, None, "a1"),
        ]
    )
    assert not errors, f"{type(errors[0]).__name__}: {errors[0]}"
    rows = env.store.overrides("attach_overrides", "clean")
    assert len(rows) == 2 and len({seq for seq, _d, _b in rows}) == 2


def test_concurrent_bbox_overrides_get_distinct_seqs(env: Env) -> None:
    blk = next(
        b
        for b in env.data.raw_blocks("clean")
        if b.type == BlockType.figure and b.bbox is not None and b.figure_id
    )
    assert blk.bbox is not None and blk.figure_id is not None
    x0, y0, x1, y1 = blk.bbox
    fid = blk.figure_id
    _rendezvous(env, "next_figure_override_seq")
    out, errors = _both(
        [
            lambda: env.figures.set_bbox(fid, [x0 + 1, y0 + 1, x1 - 1, y1 - 1], "b1"),
            lambda: env.figures.set_bbox(fid, [x0 + 2, y0 + 2, x1 - 2, y1 - 2], "b2"),
        ]
    )
    assert not errors, f"{type(errors[0]).__name__}: {errors[0]}"
    rows = env.store.figure_overrides("clean")
    assert len(rows) == 2 and len({r[0] for r in rows}) == 2


def test_concurrent_snapshots_get_distinct_ids(env: Env) -> None:
    from manuallabor.state.learning import LearningService

    svc = LearningService(env.paths, env.store)
    env.act("approve", env.review.queue(None, None, "clean", 5, 0).items[0].block_id)
    _rendezvous(env, "next_snapshot_id")
    out, errors = _both([lambda: svc.snapshot("s1"), lambda: svc.snapshot("s2")])
    assert not errors, f"{type(errors[0]).__name__}: {errors[0]}"
    ids = sorted(s.id for s in env.store.snapshots())
    assert ids == ["001", "002"]
    assert sorted(p.name for p in (env.paths.learning / "snapshots").iterdir()) == ids
