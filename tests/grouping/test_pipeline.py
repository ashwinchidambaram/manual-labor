"""Pipeline, persistence, determinism, overrides, learning, performance (design tests 3, 27-35)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from manuallabor import ids
from manuallabor.cli import app
from manuallabor.contracts import Task
from manuallabor.contracts.enums import BlockType, GroupView, TitleSource, UnassignedReason
from manuallabor.contracts.group import GroupOverride, GroupsFile
from manuallabor.contracts.io import read_json, write_json
from manuallabor.grouping.learning import LearnedGrouping, RegroupExample
from manuallabor.grouping.mock_replies import mock_grouping_reply
from manuallabor.grouping.pipeline import check_partition, group_document
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider, ProviderError
from manuallabor.scoring.pipeline import run_score
from tests.conftest import Scored
from tests.grouping.conftest import Grouped, copy_project, doc_of, heading, mk, provider_set

REPO = Path(__file__).resolve().parents[2]
Collect = Callable[..., tuple[list[str], list[dict[str, Any]]]]


def _bytes(paths: ProjectPaths, slug: str) -> bytes:
    return paths.doc(slug).groups.read_bytes()


# ---------------------------------------------------------------------------------------------
# partition check


def test_check_partition_catches_defects(grouped: Grouped) -> None:
    gf, blocks = grouped.gf("clean"), grouped.blocks("clean")
    assert check_partition(blocks, gf) == []

    s = list(gf.structure)
    s[1] = s[1].model_copy(
        update={"block_ids": s[1].block_ids[:-1], "block_count": s[1].block_count - 1}
    )
    dropped = check_partition(blocks, gf.model_copy(update={"structure": s}))
    assert any("is in no group" in p for p in dropped)

    s = list(gf.structure)
    extra = s[3].block_ids[0]
    s[2] = s[2].model_copy(
        update={"block_ids": [*s[2].block_ids, extra], "block_count": s[2].block_count + 1}
    )
    dup = check_partition(blocks, gf.model_copy(update={"structure": s}))
    assert any("appears 2 times" in p for p in dup)

    t = list(gf.topics)
    t[1] = t[1].model_copy(
        update={
            "block_ids": [*t[1].block_ids, "b-other-p001-01"],
            "block_count": t[1].block_count + 1,
        }
    )
    foreign = check_partition(blocks, gf.model_copy(update={"topics": t}))
    assert any("unknown block" in p for p in foreign)

    thin = list(gf.topics)
    thin[1] = thin[1].model_copy(update={"cohesion": None})
    assert any(
        "cohesion" in p for p in check_partition(blocks, gf.model_copy(update={"topics": thin}))
    )


def test_partition_failure_writes_nothing_and_exits_1(
    scored_copy: ProjectPaths, monkeypatch: pytest.MonkeyPatch, run_and_collect: Collect
) -> None:
    monkeypatch.setattr("manuallabor.grouping.pipeline.check_partition", lambda b, g: ["boom"])
    failed, lines = run_and_collect(scored_copy, only="manual")
    assert failed == ["manual"] and not scored_copy.doc("manual").groups.exists()
    assert lines[-1]["status"] == "error" and "boom" in lines[-1]["detail"]
    r = CliRunner().invoke(app, ["group", str(scored_copy.root), "--doc", "manual"])
    assert r.exit_code == 1 and not scored_copy.doc("manual").groups.exists()


# ---------------------------------------------------------------------------------------------
# idempotence, determinism, fingerprint


def test_group_is_idempotent_and_force_rewrites_identical_bytes(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    failed, first = run_and_collect(scored_copy)
    assert failed == [] and {x["status"] for x in first} == {"done"}
    assert [x["doc"] for x in first] == sorted(x["doc"] for x in first)
    before = {
        s: (_bytes(scored_copy, s), scored_copy.doc(s).groups.stat().st_mtime_ns)
        for s in scored_copy.list_slugs()
    }
    failed, second = run_and_collect(scored_copy)
    assert failed == [] and {x["status"] for x in second} == {"skip"}
    for s, (data, mtime) in before.items():
        assert (
            _bytes(scored_copy, s) == data and scored_copy.doc(s).groups.stat().st_mtime_ns == mtime
        )
    failed, third = run_and_collect(scored_copy, force=True)
    assert {x["status"] for x in third} == {"done"}
    for s, (data, _) in before.items():
        assert _bytes(scored_copy, s) == data
    assert set(first[0]) == {
        "doc", "stage", "status", "structure_groups", "topics", "unassigned", "low_cohesion",
        "stragglers", "llm_fallbacks", "elapsed_ms", "detail",
    }  # fmt: skip


def test_groups_json_is_byte_identical_across_processes(
    scoredproj: Scored, scored_copy: ProjectPaths, tmp_path: Path
) -> None:
    other = copy_project(scoredproj.paths.root, tmp_path / "second")
    code = "from manuallabor.cli import app; app()"
    for paths, seed in ((scored_copy, "1"), (other, "2")):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run(
            [sys.executable, "-c", code, "group", str(paths.root)],
            cwd=REPO, env=env, capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
    for slug in scored_copy.list_slugs():
        assert _bytes(scored_copy, slug) == _bytes(other, slug)


def _config_edit(paths: ProjectPaths, **update: Any) -> None:
    cfg = paths.load_config()
    data = {**cfg.model_dump(mode="json"), **update}
    write_json(paths.config, type(cfg).model_validate(data))


def test_fingerprint_invalidation(scored_copy: ProjectPaths, run_and_collect: Collect) -> None:
    p, doc = scored_copy, "manual"

    def status() -> str:
        failed, lines = run_and_collect(p, only=doc)
        assert failed == []
        return str(lines[-1]["status"])

    assert status() == "done" and status() == "skip"
    blocks_path = p.doc(doc).blocks
    blocks_path.write_text(
        json.dumps(json.loads(blocks_path.read_text()), indent=4), encoding="utf-8"
    )
    assert status() == "done" and status() == "skip"
    models = p.load_config().model_dump(mode="json")["models"]
    models["embeddings"]["model"] = "mock-2"
    _config_edit(p, models=models)
    assert status() == "done"
    assert read_json(p.doc(doc).groups, GroupsFile).embedding_model == "mock:mock-2"
    write_json(
        p.doc(doc).group_overrides,
        [GroupOverride(seq=1, kind="move", block_id="b-manual-p001-01", to_topic_slug="vanished")],
    )
    assert status() == "done"
    assert read_json(p.doc(doc).groups, GroupsFile).overrides_stale == [0]
    write_json(p.learned_grouping, LearnedGrouping(snapshot="snap-1"))
    assert status() == "skip"  # learning is still off
    _config_edit(p, learning={"enabled": True})
    assert status() == "done"
    assert read_json(p.doc(doc).groups, GroupsFile).learning_snapshot == "snap-1"
    # a new confidence threshold restates scores.json but must not invalidate grouping
    _config_edit(p, threshold=0.5)
    assert run_score(p, only=doc, emit=lambda _o: None) == []
    assert status() == "skip"


def test_fully_mocked_run_needs_no_canned_responses(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    failed, lines = run_and_collect(scored_copy)
    assert failed == [] and {x["status"] for x in lines} == {"done"} and len(lines) == 6
    log = [json.loads(x) for x in (scored_copy.root / "llm_calls.jsonl").read_text().splitlines()]
    assert {e["task"] for e in log} >= {"grouping", "embeddings"}
    assert all(e["ok"] for e in log)


def test_mock_namespace_does_not_depend_on_importing_grouping() -> None:
    base = (
        "from manuallabor.providers import ListSink, MockProvider\n"
        "print(MockProvider(sink=ListSink()).cache_namespace)"
    )
    outs = []
    for code in (base, "import manuallabor.grouping.pipeline\n" + base):
        r = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
        )
        outs.append(r.stdout.strip())
    assert outs[0] == outs[1] and outs[0].startswith("mock:mock-1:MockProvider:")


# ---------------------------------------------------------------------------------------------
# topic failure


class FailingEmbedder(MockProvider):
    def _embed_raw(self, task: Task, texts: Sequence[str]):  # type: ignore[no-untyped-def]
        raise ProviderError("embedding service is down", provider="mock", model="mock-1", task=task)


def test_topic_failure_keeps_structure_and_exits_nonzero(
    scored_copy: ProjectPaths, run_and_collect: Collect
) -> None:
    sink = ListSink()
    ps = provider_set(sink, embeddings=FailingEmbedder(sink=sink))
    failed, lines = run_and_collect(scored_copy, only="clean", providers=ps)
    assert failed == ["clean"] and lines[-1]["status"] == "topic_failed"
    gf = read_json(scored_copy.doc("clean").groups, GroupsFile)
    blocks = [b for b in _blocks(scored_copy, "clean")]
    assert gf.topic_status == "failed" and gf.topic_error and gf.embedding_dim == 0
    assert len(gf.structure) == 18 and [t.id for t in gf.topics] == ["g-clean-t000"]
    body = {b.id for b in blocks if b.type not in (BlockType.header, BlockType.footer)}
    assert set(gf.topics[0].block_ids) == body
    reasons = {u.reason for u in gf.unassigned if u.view == GroupView.topic}
    assert reasons == {UnassignedReason.topic_failed, UnassignedReason.header_footer}
    assert check_partition(blocks, gf) == []
    r = CliRunner().invoke(app, ["group", str(scored_copy.root), "--doc", "no-such-doc"])
    assert r.exit_code == 1


def _blocks(paths: ProjectPaths, slug: str) -> list[Any]:
    from manuallabor.scoring.pipeline import load_scored_blocks

    return load_scored_blocks(paths, slug)


# ---------------------------------------------------------------------------------------------
# overrides and learning


def test_overrides_apply_and_stale_ones_are_reported(grouped: Grouped) -> None:
    doc, blocks = grouped.scored.doc("clean"), grouped.blocks("clean")
    ps = lambda: provider_set(ListSink())  # noqa: E731
    base = group_document(doc, blocks, ps())
    topics = [t for t in base.topics if not t.is_unassigned and t.block_count >= 4]
    src, dst = topics[0], topics[1]
    stragglers = {r.block_id for r in base.stragglers}
    moved = next(b for b in src.block_ids if b not in stragglers)
    other = next(b for b in dst.block_ids if b not in stragglers)
    ov = [
        GroupOverride(seq=1, kind="move", block_id=moved, to_topic_slug=dst.slug),
        GroupOverride(seq=2, kind="move", block_id=other, to_topic_slug="vanished-topic"),
        GroupOverride(seq=3, kind="rename", topic_slug=src.slug, title="  Custom   title "),
    ]
    gf = group_document(doc, blocks, ps(), overrides=ov)
    by_slug = {t.slug: t for t in gf.topics}
    assert moved in by_slug[dst.slug].block_ids and moved not in by_slug[src.slug].block_ids
    assert other in by_slug[dst.slug].block_ids  # the stale move left it where it was
    assert gf.overrides_applied == 2 and gf.overrides_stale == [1]
    assert by_slug[src.slug].title == "Custom title"  # slug (the article id) is unchanged
    assert gf.title_sources[by_slug[src.slug].id] == TitleSource.human
    assert check_partition(blocks, gf) == []
    # moving to `unassigned` puts the block in t000
    gf2 = group_document(
        doc, blocks, ps(),
        overrides=[GroupOverride(seq=1, kind="move", block_id=moved, to_topic_slug="unassigned")],
    )  # fmt: skip
    assert moved in gf2.topics[0].block_ids and check_partition(blocks, gf2) == []


def test_learning_off_is_the_baseline(scored_copy: ProjectPaths, run_and_collect: Collect) -> None:
    p = scored_copy
    run_and_collect(p, only="manual")
    baseline = _bytes(p, "manual")
    example = RegroupExample(
        doc_id="manual", summary="s", from_title="a", to_title="b", kind="move"
    )
    write_json(p.learned_grouping, LearnedGrouping(snapshot="snap-1", examples=[example]))
    run_and_collect(p, only="manual", force=True)
    assert _bytes(p, "manual") == baseline
    assert read_json(p.doc("manual").groups, GroupsFile).learning_snapshot == "baseline"
    _config_edit(p, learning={"enabled": True})
    run_and_collect(p, only="manual")
    assert read_json(p.doc("manual").groups, GroupsFile).learning_snapshot == "snap-1"
    _config_edit(p, learning={"enabled": False})
    run_and_collect(p, only="manual")
    assert _bytes(p, "manual") == baseline


def test_learned_examples_reach_the_prompt_only_when_provided(grouped: Grouped) -> None:
    doc, blocks = grouped.scored.doc("manual"), grouped.blocks("manual")
    seen: list[dict[str, Any]] = []

    def spy(messages):  # type: ignore[no-untyped-def]
        seen.append(json.loads(messages[1].content[len("<input>") : -len("</input>")]))
        return mock_grouping_reply(messages)

    example = RegroupExample(
        doc_id="manual", summary="s", from_title="a", to_title="b", kind="rename"
    )
    learned = LearnedGrouping(snapshot="snap-1", examples=[example])
    group_document(doc, blocks, provider_set(ListSink(), grouping=spy))
    assert seen and all("examples" not in x for x in seen)
    seen.clear()
    group_document(doc, blocks, provider_set(ListSink(), grouping=spy), learned=learned)
    assert seen and all(x["examples"][0]["to_title"] == "b" for x in seen)


# ---------------------------------------------------------------------------------------------
# performance


def test_three_thousand_blocks_under_five_seconds() -> None:
    blocks = []
    for i in range(3000):
        page, n = i // 30 + 1, i % 30 + 1
        if i % 40 == 0:
            blocks.append(
                heading(
                    page,
                    n,
                    f"{i // 40 + 1}. Section {i // 40}",
                    heading_level=1,
                    section_number=str(i // 40 + 1),
                )
            )
        else:
            topic = (i // 40) % 25
            words = " ".join(f"w{(topic * 7 + j * 13 + i % 5) % 400}" for j in range(20))
            blocks.append(mk(page, n, words))
    ps = provider_set(ListSink())
    t0 = time.perf_counter()
    gf = group_document(doc_of(blocks), blocks, ps)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"{elapsed:.2f}s"
    assert check_partition(blocks, gf) == []
    assert all(t.block_count <= 3000 for t in gf.topics)
    assert ids.block_sort_key(gf.topics[1].block_ids[0])
