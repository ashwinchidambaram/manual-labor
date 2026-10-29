"""Test 20: `labor score`, the scores.json overlay, skip/force, determinism, sidecars, history."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from manuallabor.cli import app
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json, read_json_list, write_json
from manuallabor.figures.pipeline import run_figures
from manuallabor.project import ProjectPaths
from manuallabor.scoring.pipeline import load_scored_blocks, run_score
from manuallabor.scoring.types import ScoreFile

runner = CliRunner()


def snapshot(paths: ProjectPaths) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        for p in (dp.scores, dp.score_history, dp.blocks):
            if p.is_file():
                out[str(p.relative_to(paths.root))] = p.read_bytes()
    for p in sorted(paths.figures_root.rglob("FIG-*.json")):
        out[str(p.relative_to(paths.root))] = p.read_bytes()
    return out


def _lines(output: str) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in output.splitlines() if ln.startswith("{")]


def _copy(src: Path, dst: Path) -> ProjectPaths:
    shutil.copytree(src, dst)
    return ProjectPaths(dst)


def test_cli_end_to_end(figproj_scoring: ProjectPaths, tmp_path: Path) -> None:
    paths = _copy(figproj_scoring.root, tmp_path / "a")
    blocks_before = {s: paths.doc(s).blocks.read_bytes() for s in paths.list_slugs()}

    res = runner.invoke(app, ["score", str(paths.root)])
    assert res.exit_code == 0, res.output
    lines = _lines(res.output)
    assert [ln["doc"] for ln in lines] == paths.list_slugs()
    assert all(ln["stage"] == "score" and ln["status"] == "done" for ln in lines)
    keys = {
        "doc",
        "stage",
        "status",
        "blocks",
        "auto_approved",
        "queued",
        "numeric",
        "figures",
        "faith_failed",
        "elapsed_ms",
        "detail",
    }
    assert all(set(ln) == keys for ln in lines)

    for slug in paths.list_slugs():
        dp = paths.doc(slug)
        assert dp.blocks.read_bytes() == blocks_before[slug]  # blocks.json is parse-owned
        sf = read_json(dp.scores, ScoreFile)
        blocks = read_json_list(dp.blocks, Block)
        assert sorted(s.block_id for s in sf.blocks) == sorted(b.id for b in blocks)
        merged = load_scored_blocks(paths, slug)
        assert all(isinstance(b, Block) and b.signals for b in merged)
        assert all(
            b.confidence is not None
            for b in merged
            if b.raw_text.strip() or b.type == BlockType.figure
        )

    # second run: skip, nothing rewritten
    snap = snapshot(paths)
    res = runner.invoke(app, ["score", str(paths.root)])
    assert res.exit_code == 0
    assert all(ln["status"] == "skip" for ln in _lines(res.output))
    assert snapshot(paths) == snap

    # --force: re-scored, identical bytes, history not appended (nothing changed)
    res = runner.invoke(app, ["score", str(paths.root), "--force"])
    assert res.exit_code == 0
    assert all(ln["status"] == "done" for ln in _lines(res.output))
    assert snapshot(paths) == snap

    # another process with a different hash seed: byte-identical outputs
    other = _copy(figproj_scoring.root, tmp_path / "b")
    env = {**os.environ, "PYTHONHASHSEED": "123"}
    proc = subprocess.run(
        [sys.executable, "-c", "from manuallabor.cli import app; app()", "score", str(other.root)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    snap_b = snapshot(other)
    assert snap_b.keys() == snap.keys()
    assert [k for k in snap if snap[k] != snap_b[k]] == []

    # `labor figures --force` resets sidecar confidence; score restores it without re-scoring
    assert run_figures(paths, force=True, emit=lambda _o: None) == []
    reset = read_json(paths.figure_file("scanned", "FIG-scanned-p005-01", "json"), FigureRecord)
    assert reset.confidence == 0.7  # provisional crop value from module 2
    res = runner.invoke(app, ["score", str(paths.root)])
    st = {ln["doc"]: ln["status"] for ln in _lines(res.output)}
    assert st["scanned"] == "sidecars" and st["tables"] == "skip"
    assert snapshot(paths) == snap


def test_rescore_on_change_and_history(scored_copy: ProjectPaths) -> None:
    paths = scored_copy
    dp = paths.doc("clean")
    hist_before = dp.score_history.read_text().splitlines()
    blocks = read_json_list(dp.blocks, Block)
    i = next(
        i for i, b in enumerate(blocks) if b.type == BlockType.paragraph and "35" not in b.raw_text
    )
    target = blocks[i]
    texts = dict(target.raw_text_by_parser)
    texts["docling"] = texts["docling"].replace(" ", "  X ", 1)
    blocks[i] = target.model_copy(update={"raw_text_by_parser": texts})
    write_json(dp.blocks, blocks)  # as a parse re-run with different output would
    out: list[dict[str, object]] = []
    assert run_score(paths, emit=out.append) == []
    st = {ln["doc"]: ln["status"] for ln in out}
    assert st["clean"] == "done" and st["tables"] == "skip"
    hist_after = dp.score_history.read_text().splitlines()
    added = hist_after[len(hist_before) :]
    assert len(added) == 1
    h = json.loads(added[0])
    assert h["block_id"] == target.id and h["seq"] == len(hist_before) + 1


def test_missing_figures_report_errors_one_doc(scored_copy: ProjectPaths) -> None:
    paths = scored_copy
    paths.doc("figures").figure_report.unlink()
    res = runner.invoke(app, ["score", str(paths.root), "--force"])
    assert res.exit_code == 1
    st = {ln["doc"]: ln for ln in _lines(res.output)}
    assert st["figures"]["status"] == "error" and "figures_report" in str(st["figures"]["detail"])
    assert all(v["status"] == "done" for k, v in st.items() if k != "figures") and len(st) == 6
    bad = runner.invoke(app, ["score", str(paths.root), "--doc", "no-such-doc"])
    assert bad.exit_code == 1


def test_doc_option(scored_copy: ProjectPaths) -> None:
    res = runner.invoke(app, ["score", str(scored_copy.root), "--doc", "manual", "--force"])
    assert res.exit_code == 0
    assert [ln["doc"] for ln in _lines(res.output)] == ["manual"]


def test_threshold_change_restatus_without_rescoring(
    scored_copy: ProjectPaths, tmp_path: Path
) -> None:
    paths = scored_copy
    forced = _copy(paths.root, tmp_path / "forced")
    for p in (paths, forced):
        cfg = p.load_config()
        write_json(p.config, cfg.model_copy(update={"threshold": 0.4}))
    out: list[dict[str, object]] = []
    assert run_score(paths, emit=out.append) == []
    assert all(ln["status"] == "restatus" for ln in out)
    assert run_score(forced, force=True, emit=lambda _o: None) == []
    for slug in paths.list_slugs():
        a = paths.doc(slug).scores.read_bytes()
        assert a == forced.doc(slug).scores.read_bytes()  # same result as a full re-score
        sf = read_json(paths.doc(slug).scores, ScoreFile)
        assert sf.threshold == 0.4
        assert all(s.status == "queued" for s in sf.blocks if s.has_numeric_spec)


# -- uncovered branches named by the review -------------------------------------------------


def test_raw_vs_raw_self_test_failure_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A canonicalizer that cannot pass raw vs raw is a bug: the document fails loudly
    instead of every block silently getting faithfulness 1.0."""
    import pytest

    from manuallabor.contracts.block import FaithfulnessResult, FaithfulnessViolation
    from manuallabor.contracts.enums import FaithViolationKind
    from manuallabor.scoring import pipeline as P
    from manuallabor.scoring.faithfulness import FaithOutcome
    from manuallabor.scoring.types import ScoringError
    from tests.scoring.conftest import ctx, make_block

    def broken(raw: str, clean: str, **_kw: object) -> FaithOutcome:
        v = FaithfulnessViolation(
            kind=FaithViolationKind.deletion,
            raw_start=0,
            raw_end=0,
            clean_start=0,
            clean_end=0,
            raw="",
            clean="",
        )
        res = FaithfulnessResult(passed=False, alignment_ratio=0.0, violations=[v], diff=[])
        return FaithOutcome(res, False)

    monkeypatch.setattr(P, "check_faithfulness_ex", broken)
    with pytest.raises(ScoringError, match="self-test failed"):
        P.score_block(make_block("Check the drive belt."), ctx(), threshold=0.85)


def test_run_score_with_mock_verifier(scored_copy: ProjectPaths) -> None:
    """End to end: cleaned blocks go through run_score with a separate MockProvider verifier;
    a found span becomes a 0.2 soft signal on that block only, NONE adds nothing."""
    from collections.abc import Sequence

    from manuallabor.contracts.config import ModelRef
    from manuallabor.contracts.enums import SignalName, Task
    from manuallabor.contracts.llm import Message
    from manuallabor.providers import ListSink, MockProvider, ProviderSet
    from manuallabor.providers.cache import LLMCache

    paths = scored_copy
    cfg = json.loads(paths.config.read_text())
    cfg["models"]["verifier"]["model"] = "mock-verifier"  # not the cleanup model
    paths.config.write_text(json.dumps(cfg))
    dp = paths.doc("clean")
    blocks = read_json_list(dp.blocks, Block)
    paras = [b for b in blocks if b.type == BlockType.paragraph and "\n" in b.raw_text.strip()][:3]
    assert len(paras) == 3
    cleaned = {b.id: " ".join(b.raw_text.replace("-\n", "").split()) for b in paras}
    flagged_id = paras[0].id
    span = cleaned[flagged_id].split()[1] + " " + cleaned[flagged_id].split()[2]
    write_json(
        dp.blocks,
        [b.model_copy(update={"clean_text": cleaned.get(b.id)}) for b in blocks],
    )

    def responder(messages: Sequence[Message]) -> str:
        return span if cleaned[flagged_id] in messages[-1].content else "NONE"

    sink = ListSink()
    prov = MockProvider(
        ModelRef(provider="mock", model="mock-verifier"),
        sink=sink,
        cache=LLMCache(paths.root / ".llm_cache"),
        responses={Task.verifier: responder},
    )
    lines: list[dict[str, object]] = []
    failed = run_score(
        paths,
        only="clean",
        force=True,
        providers=ProviderSet(by_task={Task.verifier: prov}),
        emit=lines.append,
    )
    assert failed == []
    assert len(sink) == 3  # one call per cleaned block, nothing else
    detail = str(lines[-1]["detail"])
    assert "verifier_flagged: 1" in detail and "verifier_ok: 2" in detail
    sf = read_json(dp.scores, ScoreFile)
    by_id = {s.block_id: s for s in sf.blocks}
    for b in paras:
        sig = [s for s in by_id[b.id].signals if s.name == SignalName.llm_verifier]
        assert by_id[b.id].faithfulness is not None and by_id[b.id].faithfulness.passed
        if b.id == flagged_id:
            assert [s.value for s in sig] == [0.2] and span in (sig[0].detail or "")
            assert by_id[b.id].status == "queued"
        else:
            assert sig == []
