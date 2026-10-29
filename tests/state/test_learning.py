"""L1-L7: the reversible learning layer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from manuallabor.contracts.enums import BlockType
from manuallabor.jobs.inline import run_inline
from manuallabor.project import ProjectPaths
from manuallabor.state.errors import InvalidOp
from manuallabor.state.learning import LearningService, derive_snapshot_files
from manuallabor.state.models import RunPlanIn
from tests.state.helpers import Env


@pytest.fixture
def env(lp: ProjectPaths) -> Iterator[Env]:
    e = Env(lp)
    yield e
    e.close()


def rerun(env: Env, *force: str) -> None:
    res = run_inline(
        env.paths,
        RunPlanIn(to="score2", force=list(force)),
        mode="mock",
        emit=lambda _o: None,
        store=env.store,
    )
    assert res.ok


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snap_tree(paths: ProjectPaths, sid: str) -> dict[str, str]:
    d = paths.snapshot_dir(sid)
    return {f.name: sha(f) for f in sorted(d.iterdir())}


def teach(env: Env, n: int = 4) -> list[str]:
    """Approve blocks whose cleanup changed the text and make one lossless edit."""
    page = env.review.queue(None, 1.0, None, 5000, 0)
    done: list[str] = []
    for item in page.items:
        if item.type != BlockType.paragraph or len(done) >= n:
            continue
        b = {x.id: x for x in env.blocks(item.doc_id)}[item.block_id]
        if b.clean_text in (None, b.raw_text):
            continue
        env.act(
            "edit" if len(done) == 0 else "approve",
            b.id,
            **({"text": b.clean_text} if not done else {}),
        )
        done.append(b.id)
    assert len(done) == n
    return done


def baseline_bytes(paths: ProjectPaths) -> dict[str, bytes]:
    return {
        f"{s}/{n}": paths.doc(s).root.joinpath(n).read_bytes()
        for s in paths.list_slugs()
        for n in ("groups.json", "clean.json", "scores.json", "attach.json")
    }


def test_l1_toggle_off_is_baseline_even_with_an_active_snapshot(env: Env) -> None:
    base = baseline_bytes(env.paths)
    teach(env)
    svc = LearningService(env.paths, env.store)
    svc.activate(svc.snapshot("s1").id, "a1")
    assert svc.state().enabled is False and svc.state().provenance == "baseline"
    assert env.paths.learned_cleanup.is_file()  # materialized, but unused
    rerun(env, "group", "clean")
    after = baseline_bytes(env.paths)
    # the decisions changed scores' human state only in the DB; stage outputs equal a project
    # that never had a learning/ directory
    assert {k: v for k, v in after.items() if not k.endswith("scores.json")} == {
        k: v for k, v in base.items() if not k.endswith("scores.json")
    }
    assert json.loads(after["clean/clean.json"])["learning_snapshot"] == "baseline"


def test_l2_snapshot_derivation(env: Env) -> None:
    ids = teach(env, 5)
    svc = LearningService(env.paths, env.store)
    s1 = svc.snapshot("s1")
    assert s1.id == "001" and s1.parent is None and s1.active is False
    files, counts = derive_snapshot_files(env.store, "snapshot:001")
    assert files == derive_snapshot_files(env.store, "snapshot:001")[0]  # deterministic bytes
    cleanup = json.loads(files["cleanup.json"])
    assert cleanup["snapshot"] == "snapshot:001" and cleanup["rules"] == []
    assert counts["cleanup"] == len(cleanup["examples"]) == 5
    for ex in cleanup["examples"]:
        assert ex["clean"] != ex["raw"] and ex["id"].startswith("ex-")
    on_disk = env.paths.snapshot_dir("001")
    assert (on_disk / "cleanup.json").read_text() == files["cleanup.json"]
    manifest = json.loads((on_disk / "manifest.json").read_text())
    assert manifest["id"] == "001" and manifest["source_action_range"] == [
        1,
        env.store.max_action_id() - 1,
    ]
    before = snap_tree(env.paths, "001")
    env.act("skip", next(i.block_id for i in env.review.queue(None, None, None, 5, 0).items))
    s2 = svc.snapshot("s2")
    assert s2.id == "002" and s2.parent == "001"
    assert snap_tree(env.paths, "001") == before  # immutable
    assert ids  # decisions kept
    # a flagged or lossy edit never becomes an example
    assert all(e["id"] != "ex-0" for e in json.loads(files["cleanup.json"])["examples"])


def test_l3_activate_rollback_reset(env: Env) -> None:
    base = baseline_bytes(env.paths)
    teach(env, 3)
    svc = LearningService(env.paths, env.store)
    svc.snapshot("s1")
    teach_more = [i.block_id for i in env.review.queue(None, 1.0, None, 40, 0).items][-2:]
    for b in teach_more:
        env.act("skip", b)
    svc.snapshot("s2")
    svc.set_flags(True, None, None, "on")
    svc.activate("002", "act2")
    p = env.paths
    assert (p.learned_cleanup).read_text() == (p.snapshot_dir("002") / "cleanup.json").read_text()
    assert (p.learned_grouping).read_text() == (p.snapshot_dir("002") / "grouping.json").read_text()
    assert json.loads(p.learning_active.read_text()) == {"id": "002", "provenance": "snapshot:002"}
    rerun(env)
    for slug in p.list_slugs():
        assert json.loads(p.doc(slug).clean.read_text())["learning_snapshot"] == "snapshot:002"
        assert json.loads(p.doc(slug).groups.read_text())["learning_snapshot"] == "snapshot:002"
    svc.activate("001", "roll")  # rollback is the same operation
    rerun(env)
    assert json.loads(p.doc("clean").clean.read_text())["learning_snapshot"] == "snapshot:001"
    # reset removes the layer; snapshots and decisions stay
    n_dec = len(env.store.decisions())
    svc.reset("rst")
    assert not p.learned_cleanup.exists() and not p.learned_grouping.exists()
    assert not p.learning_active.exists()
    assert p.snapshot_dir("001").is_dir() and p.snapshot_dir("002").is_dir()
    assert len(env.store.decisions()) == n_dec
    rerun(env)
    assert {k: v for k, v in baseline_bytes(p).items() if not k.endswith("scores.json")} == {
        k: v for k, v in base.items() if not k.endswith("scores.json")
    }
    assert svc.state().provenance == "baseline" and svc.state().active is None


def test_l4_learning_never_touches_the_config(env: Env) -> None:
    teach(env, 3)
    cfg_before = env.paths.config.read_bytes()
    svc = LearningService(env.paths, env.store)
    s = svc.snapshot("a")
    svc.activate(s.id, "b")
    ex = json.loads(env.paths.snapshot_dir(s.id).joinpath("cleanup.json").read_text())["examples"][
        0
    ]
    svc.disable_item(ex["id"], "c")
    svc.activate("001", "d")
    svc.reset("e")
    assert env.paths.config.read_bytes() == cfg_before
    # only PUT /api/learning (set_flags) changes `learning.*`, and nothing else
    svc.set_flags(True, True, None, "f")
    old, new = json.loads(cfg_before), json.loads(env.paths.config.read_text())
    assert {k for k in new if new[k] != old.get(k)} == {"learning"}
    assert new["learning"] == {"enabled": True, "use_global": True, "contribute_global": False}


def test_l5_global_store(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("MANUALLABOR_HOME", str(home))
    teach(env, 3)
    svc = LearningService(env.paths, env.store)
    s = svc.snapshot("a")
    with pytest.raises(InvalidOp, match="contribute_global"):
        svc.publish(s.id, "p0")
    assert not home.exists()
    svc.set_flags(None, None, True, "cg")
    svc.publish(s.id, "p1")
    g = home / "learning" / "snapshots" / "001"
    assert json.loads((g / "cleanup.json").read_text())["snapshot"] == "global:001"
    assert json.loads((g / "manifest.json").read_text())["origin"].startswith("project:")
    # a second project with use_global and no snapshot of its own uses the global one
    from tests.conftest import labor_copy

    other = ProjectPaths(labor_copy(env.paths.root, tmp_path / "other"))
    for f in other.learning.glob("**/*"):
        if f.is_file():
            f.unlink()
    import shutil

    shutil.rmtree(other.learning, ignore_errors=True)
    other.db.unlink(missing_ok=True)
    e2 = Env(other)
    try:
        s2 = LearningService(other, e2.store)
        s2.set_flags(True, True, False, "u")
        assert s2.state().provenance == "global:001"
        assert json.loads(other.learned_cleanup.read_text())["snapshot"] == "global:001"
        rerun(e2)
        assert json.loads(other.doc("clean").clean.read_text())["learning_snapshot"] == "global:001"
        # project beats global (never merged)
        mine = s2.snapshot("m")
        s2.activate(mine.id, "m2")
        assert s2.state().provenance == f"snapshot:{mine.id}"
    finally:
        e2.close()


def test_l6_disable_item_creates_a_child_snapshot(env: Env) -> None:
    teach(env, 4)
    svc = LearningService(env.paths, env.store)
    first = svc.snapshot("a")
    svc.activate(first.id, "b")
    parent_tree = snap_tree(env.paths, first.id)
    items = json.loads((env.paths.snapshot_dir(first.id) / "cleanup.json").read_text())["examples"]
    victim = items[1]["id"]
    child = svc.disable_item(victim, "c")
    assert child.parent == first.id and child.active
    kept = json.loads((env.paths.snapshot_dir(child.id) / "cleanup.json").read_text())
    assert victim not in {e["id"] for e in kept["examples"]} and len(kept["examples"]) == 3
    assert kept["snapshot"] == f"snapshot:{child.id}"
    assert snap_tree(env.paths, first.id) == parent_tree
    assert svc.state().active == child.id
    assert json.loads(env.paths.learned_cleanup.read_text())["snapshot"] == f"snapshot:{child.id}"
    with pytest.raises(InvalidOp):
        svc.disable_item("ex-nope", "d")


def test_l7_decisions_by_provenance(env: Env) -> None:
    ids = teach(env, 3)
    svc = LearningService(env.paths, env.store)
    svc.set_flags(True, None, None, "on")
    svc.activate(svc.snapshot("a").id, "b")
    rerun(env)
    page = env.review.queue(None, None, None, 5, 0)
    env.act("approve", page.items[0].block_id)
    by = env.store.decisions_by_provenance()
    assert set(by) == {"baseline", "snapshot:001"}
    assert [d.decision.block_id for d in by["baseline"]] == ids
    assert [d.decision.block_id for d in by["snapshot:001"]] == [page.items[0].block_id]
