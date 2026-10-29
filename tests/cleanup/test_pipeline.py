"""Tests 34-38: the `labor clean` stage (CLI, idempotency, determinism, scoring integration,
learning hooks)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from manuallabor.cleanup.learned import load_learned_cleanup
from manuallabor.cleanup.pipeline import clean_document, cleanable
from manuallabor.cleanup.types import CleanFile, FewShotExample, LearnedCleanup, LearnedRule
from manuallabor.cli import app
from manuallabor.contracts.enums import BlockType, Task
from manuallabor.contracts.io import read_json, write_json
from manuallabor.contracts.llm import Message
from manuallabor.contracts.selection import Selection
from manuallabor.grouping.selection import load_groups, selectable_ids
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider
from manuallabor.providers.base import RawChat
from manuallabor.scoring.pipeline import load_scored_blocks, run_score
from manuallabor.scoring.types import ScoreFile, ScoringError
from tests.cleanup.conftest import Proj, doc_of, mk, quiet
from tests.conftest import copy_project

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()


def _cli(*args: str) -> tuple[int, list[dict[str, Any]]]:
    r = runner.invoke(app, ["clean", *args])
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    return r.exit_code, lines


def _outputs(paths: ProjectPaths) -> dict[str, tuple[bytes, int]]:
    out: dict[str, tuple[bytes, int]] = {}
    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        for p in (dp.clean, dp.attach, dp.describe, dp.scores):
            if p.is_file():
                out[str(p.relative_to(paths.root))] = (p.read_bytes(), p.stat().st_mtime_ns)
    for p in sorted(paths.figures_root.rglob("FIG-*.json")):
        out[str(p.relative_to(paths.root))] = (p.read_bytes(), p.stat().st_mtime_ns)
    return out


# -- 34 CLI ---------------------------------------------------------------------------------


def test_34_cli(grouped_copy: ProjectPaths) -> None:
    p = grouped_copy
    code, lines = _cli(str(p.root))
    assert code == 0
    slugs = p.list_slugs()
    assert [(x["doc"], x["stage"]) for x in lines] == [
        (s, st) for s in slugs for st in ("clean", "attach", "describe", "score")
    ]
    assert {x["status"] for x in lines} == {"done"}
    clean_line = next(x for x in lines if x["stage"] == "clean")
    assert set(clean_line) == {
        "doc", "stage", "status", "selected", "cleaned", "changed", "by_stage", "det_rejected",
        "llm_calls", "llm_cached", "llm_accepted", "llm_rejected", "residual", "elapsed_ms",
        "detail",
    }  # fmt: skip
    # no selection.json: every selectable cleanable block has an entry
    sel = selectable_ids(load_groups(p))
    for slug in slugs:
        want = {b.id for b in load_scored_blocks(p, slug) if b.id in sel and cleanable(b)}
        assert {e.block_id for e in read_json(p.doc(slug).clean, CleanFile).blocks} == want
    before = _outputs(p)
    code, lines = _cli(str(p.root))
    assert code == 0 and {x["status"] for x in lines} == {"skip"}
    assert _outputs(p) == before
    code, lines = _cli(str(p.root), "--force")
    assert code == 0
    assert {k: v[0] for k, v in _outputs(p).items()} == {k: v[0] for k, v in before.items()}
    code, lines = _cli(str(p.root), "--llm", "always", "--doc", "clean")
    st = {x["stage"]: x["status"] for x in lines}
    assert code == 0 and st == {
        "clean": "done",
        "attach": "skip",
        "describe": "skip",
        "score": "done",
    }
    assert next(x for x in lines if x["stage"] == "clean")["llm_calls"] > 0
    code, _ = _cli(str(p.root), "--llm", "sometimes")
    assert code == 2


def test_34_one_topic_selection_and_missing_groups(grouped_copy: ProjectPaths) -> None:
    p = grouped_copy
    gf = load_groups(p)["clean"]
    topic = next(t for t in gf.topics if not t.is_unassigned and len(t.block_ids) > 3)
    write_json(p.selection, Selection(block_ids=topic.block_ids))
    p.doc("manual").groups.unlink()
    code, lines = _cli(str(p.root))
    assert code == 1
    err = [x for x in lines if x["status"] == "error"]
    assert [(x["doc"], x["stage"]) for x in err] == [("manual", "clean")]
    assert "labor group" in err[0]["detail"]
    done = {x["doc"] for x in lines if x["stage"] == "score"}
    assert done == set(p.list_slugs()) - {"manual"}
    entries = read_json(p.doc("clean").clean, CleanFile).blocks
    blocks = {b.id: b for b in load_scored_blocks(p, "clean")}
    assert {e.block_id for e in entries} == {b for b in topic.block_ids if cleanable(blocks[b])}
    assert read_json(p.doc("twocol").clean, CleanFile).blocks == []


# -- 35 determinism across processes -------------------------------------------------------


def test_35_byte_identical_across_processes(groupedproj: Proj, tmp_path: Path) -> None:
    outs = []
    for seed in ("123", "7"):
        root = tmp_path / f"p{seed}"
        copy_project(groupedproj.paths.root, root)
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run(
            [sys.executable, "-c", "from manuallabor.cli import app; app()", "clean", str(root)],
            cwd=REPO, env=env, capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        outs.append({k: v[0] for k, v in _outputs(ProjectPaths(root)).items()})
    assert outs[0] == outs[1] and len(outs[0]) > 20


# -- 36 scoring integration -----------------------------------------------------------------


def test_36_scoring_integration(cleanedproj: Proj, tmp_path: Path) -> None:
    root = tmp_path / "p"
    copy_project(cleanedproj.paths.root, root)
    p = ProjectPaths(root)
    cf = read_json(p.doc("clean").clean, CleanFile)
    by_id = {b.id: b for b in load_scored_blocks(p, "clean")}
    for e in cf.blocks:
        assert by_id[e.block_id].clean_text == e.clean_text
    lines: list[dict[str, Any]] = []
    assert run_score(p, only="clean", emit=lines.append) == [] and lines[0]["status"] == "skip"
    fp0 = read_json(p.doc("clean").scores, ScoreFile).fingerprint
    # same entries, different bytes -> re-score; a fallback entry -> faithfulness 0.5 critical
    target = next(
        e
        for e in cf.blocks
        if e.stage == "deterministic" and by_id[e.block_id].type == BlockType.paragraph
    )
    blocks = [
        e.model_copy(update={"fallback": True, "passes_rejected": ["join_lines"]})
        if e.block_id == target.block_id
        else e
        for e in cf.blocks
    ]
    write_json(p.doc("clean").clean, cf.model_copy(update={"blocks": blocks}))
    lines.clear()
    assert run_score(p, only="clean", emit=lines.append) == [] and lines[0]["status"] == "done"
    assert read_json(p.doc("clean").scores, ScoreFile).fingerprint != fp0
    b = {x.id: x for x in load_scored_blocks(p, "clean")}[target.block_id]
    faith = {s.name.value: s for s in b.signals}["faithfulness"]
    assert faith.value == 0.5 and faith.critical and b.status.value == "queued"
    assert (
        faith.detail == "cleanup candidate rejected (pass: join_lines); kept deterministic result"
    )
    # an entry for an unknown block is an error, not a silent drop
    bad = cf.model_copy(
        update={
            "blocks": [*cf.blocks, cf.blocks[0].model_copy(update={"block_id": "b-clean-p099-01"})]
        }
    )
    write_json(p.doc("clean").clean, bad)
    lines.clear()
    assert run_score(p, only="clean", emit=lines.append) == ["clean"]
    assert "unknown block" in lines[0]["detail"]


def test_36_stale_clean_json_is_detected(cleanedproj: Proj, tmp_path: Path) -> None:
    """clean.json records each block's raw_text sha256; a re-parse that changed raw_text under
    the same block id makes scoring fail with "re-run `labor clean`" instead of reporting the
    stale clean text as a faithfulness failure."""
    root = tmp_path / "p"
    copy_project(cleanedproj.paths.root, root)
    p = ProjectPaths(root)
    cf = read_json(p.doc("clean").clean, CleanFile)
    raw = {b.id: b.raw_text for b in load_scored_blocks(p, "clean")}
    for e in cf.blocks:
        assert e.raw_sha256 == hashlib.sha256(raw[e.block_id].encode("utf-8")).hexdigest()
    target = next(e for e in cf.blocks if e.stage == "deterministic")
    blocks = json.loads(p.doc("clean").blocks.read_text(encoding="utf-8"))
    for b in blocks:
        if b["id"] == target.block_id:
            b["raw_text"] = b["raw_text"] + " Torque to 40 N·m."
    p.doc("clean").blocks.write_text(json.dumps(blocks), encoding="utf-8")
    lines: list[dict[str, Any]] = []
    assert run_score(p, only="clean", emit=lines.append) == ["clean"]
    assert "re-run `labor clean`" in lines[0]["detail"], lines[0]
    assert target.block_id in lines[0]["detail"]
    with pytest.raises(ScoringError, match="re-run `labor clean`"):
        load_scored_blocks(p, "clean")


# -- 37 / 38 learning -----------------------------------------------------------------------

RULES = [
    LearnedRule(
        id="r-keep",
        kind="hyphen_keep",
        value="re-enter",
        block_types=[BlockType.paragraph],
        support=3,
    ),
    LearnedRule(
        id="r-glyph", kind="bullet_glyph", value="»", block_types=[BlockType.paragraph], support=5
    ),
]


def _set_learning(p: ProjectPaths, enabled: bool) -> None:
    cfg = p.load_config()
    write_json(
        p.config,
        cfg.model_copy(update={"learning": cfg.learning.model_copy(update={"enabled": enabled})}),
    )


def test_37_learning_off_is_the_baseline(groupedproj: Proj, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    copy_project(groupedproj.paths.root, a)
    copy_project(groupedproj.paths.root, b)
    pb = ProjectPaths(b)
    write_json(pb.learned_cleanup, LearnedCleanup(snapshot="snap-1", rules=RULES))
    assert load_learned_cleanup(pb, pb.load_config()) is None
    from manuallabor.cleanup.pipeline import run_clean

    assert run_clean(ProjectPaths(a), emit=quiet) == []
    assert run_clean(pb, emit=quiet) == []
    for slug in pb.list_slugs():
        assert ProjectPaths(a).doc(slug).clean.read_bytes() == pb.doc(slug).clean.read_bytes()
        assert read_json(pb.doc(slug).clean, CleanFile).learning_snapshot == "baseline"


def test_38_learned_rules_unit(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    p = ProjectPaths(tmp_path)
    write_json(p.config, {"name": "x", "learning": {"enabled": True}})
    write_json(p.learned_cleanup, LearnedCleanup(snapshot="snap-1", rules=RULES))
    with caplog.at_level(logging.WARNING):
        learned = load_learned_cleanup(p, p.load_config())
    assert learned is not None and [r.id for r in learned.rules] == ["r-keep"]
    assert "r-glyph" in caplog.text
    blocks = [mk(1, 1, "Do not re-\nenter the tank."), mk(1, 2, "Check the\nbelt.")]
    doc = doc_of(blocks)
    sel = {b.id for b in blocks}
    entries, fp_on = clean_document(doc, blocks, [], sel, mode="off", learned=learned)
    e = entries[0]
    assert e.clean_text == "Do not re-enter the tank."
    assert e.learned_rules == ["r-keep"] and e.passes[:1] == ["learned:r-keep"] and e.faith_passed
    assert e.residual == []  # the learned rule decided the break
    base, fp_off = clean_document(doc, blocks, [], sel, mode="off")
    assert base[0].clean_text == "Do not reenter the tank." and fp_on != fp_off
    again, fp_again = clean_document(doc, blocks, [], sel, mode="off")
    assert again == base and fp_again == fp_off


def test_38_failing_learned_rule_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuallabor.cleanup import rules

    def broken(rule: LearnedRule) -> Any:
        return lambda text, ctx: text.replace("re-\nenter", "re-enter!")

    monkeypatch.setattr(rules, "learned_hyphen", broken)
    learned = LearnedCleanup(snapshot="s", rules=[RULES[0]])
    blocks = [mk(1, 1, "Do not re-\nenter the tank.")]
    entries, _ = clean_document(
        doc_of(blocks), blocks, [], {blocks[0].id}, mode="off", learned=learned
    )
    assert entries[0].passes_rejected == ["learned:r-keep"] and entries[0].fallback
    assert entries[0].clean_text == "Do not reenter the tank." and entries[0].learned_rules == []


def test_38_invalid_learned_items_are_rejected_one_by_one(grouped_copy: ProjectPaths) -> None:
    """One invalid rule no longer drops the snapshot: only it is rejected, the rest applies,
    and clean.json names what was rejected. Few-shot pairs must pass faithfulness."""
    from manuallabor.cleanup.learned import load_learned_cleanup_ex
    from manuallabor.cleanup.pipeline import run_clean

    p = grouped_copy
    rule = {"block_types": ["paragraph"], "support": 3, "enabled": True}
    store = {
        "snapshot": "snap-mixed",
        "rules": [
            {**rule, "id": "r-keep", "kind": "hyphen_keep", "value": "assem-bly"},
            {**rule, "id": "r-kind", "kind": "replace", "value": "35->36"},
            {**rule, "id": "r-glyph", "kind": "bullet_glyph", "value": "»"},
            {**rule, "id": "r-digit", "kind": "hyphen_drop", "value": "35-36"},
            {**rule, "id": "r-support", "kind": "hyphen_keep", "value": "co-owner", "support": 1},
            {**rule, "id": "r-off", "kind": "hyphen_keep", "value": "re-enter", "enabled": False},
        ],
        "examples": [
            {
                "id": "ex-ok",
                "block_type": "paragraph",
                "raw": "adjust-\nment",
                "clean": "adjustment",
            },
            {"id": "ex-digit", "block_type": "paragraph", "raw": "35 N·m", "clean": "36 N·m"},
            {
                "id": "ex-drop",
                "block_type": "paragraph",
                "raw": "Check the\nbelt.",
                "clean": "Check.",
            },
            {"id": "ex-shape", "block_type": "paragraph", "raw": "x"},
        ],
    }
    p.learned_cleanup.parent.mkdir(parents=True, exist_ok=True)
    p.learned_cleanup.write_text(json.dumps(store), encoding="utf-8")
    _set_learning(p, True)
    learned, rejected = load_learned_cleanup_ex(p, p.load_config())
    assert learned is not None and learned.snapshot == "snap-mixed"
    assert [r.id for r in learned.rules] == ["r-keep"]
    assert [e.id for e in learned.examples] == ["ex-ok"]
    assert rejected.rules == ["r-digit", "r-glyph", "r-kind", "r-support"]
    assert rejected.examples == ["ex-digit", "ex-drop", "ex-shape"]
    assert run_clean(p, only="clean", emit=quiet, rescore=False) == []
    cf = read_json(p.doc("clean").clean, CleanFile)
    assert cf.learning_snapshot == "snap-mixed"
    assert cf.rejected_rules == ["r-digit", "r-glyph", "r-kind", "r-support"]
    assert cf.rejected_examples == ["ex-digit", "ex-drop", "ex-shape"]
    used = [e for e in cf.blocks if e.learned_rules]
    assert used and all(e.learned_rules == ["r-keep"] and e.faith_passed for e in used)
    assert any("assem-bly" in e.clean_text for e in used)


class Spy(MockProvider):
    seen: list[list[Message]]

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self.seen.append(list(messages))
        return super()._chat_raw(task, messages, json_schema, temperature)


def test_38_few_shot_examples() -> None:
    exs = [
        FewShotExample(id="ex-far", block_type=BlockType.heading, raw="A-\nB", clean="A-B"),
        FewShotExample(
            id="ex-2",
            block_type=BlockType.paragraph,
            residual=["ambiguous_hyphen"],
            raw="co-\nowner x",
            clean="coowner x",
        ),
        FewShotExample(
            id="ex-1",
            block_type=BlockType.paragraph,
            residual=["ambiguous_hyphen"],
            raw="pre-\nset value here",
            clean="preset value here",
        ),
        FewShotExample(
            id="ex-ocr", block_type=BlockType.paragraph, ocr=True, raw="x\ny", clean="x y"
        ),
    ]
    learned = LearnedCleanup(snapshot="s", examples=exs)
    prov = Spy(sink=ListSink())
    prov.seen = []
    blocks = [mk(1, 1, "Do not re-\nenter it.")]
    entries, _ = clean_document(
        doc_of(blocks), blocks, [], {blocks[0].id}, mode="always", provider=prov, learned=learned
    )
    msgs = prov.seen[0]
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert msgs[1].content == "<raw>pre-\nset value here</raw>"
    assert msgs[2].content == "preset value here"
    assert msgs[3].content == "<raw>co-\nowner x</raw>"
    assert entries[0].few_shot == ["ex-1", "ex-2"]
    # learning off: no examples in the prompt
    prov.seen = []
    entries, _ = clean_document(
        doc_of(blocks), blocks, [], {blocks[0].id}, mode="always", provider=prov
    )
    assert [m.role for m in prov.seen[0]] == ["system", "user"] and entries[0].few_shot == []


def test_38_toggling_learning_reproduces_baseline(grouped_copy: ProjectPaths) -> None:
    from manuallabor.cleanup.pipeline import run_clean

    p = grouped_copy
    assert run_clean(p, only="clean", emit=quiet, rescore=False) == []
    base = p.doc("clean").clean.read_bytes()
    write_json(p.learned_cleanup, LearnedCleanup(snapshot="snap-9", rules=RULES))
    _set_learning(p, True)
    assert run_clean(p, only="clean", emit=quiet, rescore=False) == []
    on = read_json(p.doc("clean").clean, CleanFile)
    assert on.learning_snapshot == "snap-9" and p.doc("clean").clean.read_bytes() != base
    _set_learning(p, False)
    assert run_clean(p, only="clean", emit=quiet, rescore=False) == []
    assert p.doc("clean").clean.read_bytes() == base
