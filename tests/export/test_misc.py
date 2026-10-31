"""E18 (README), P8 (size warning), model provenance and the smaller branches of the package."""

from __future__ import annotations

import json
import re
from pathlib import Path

from manuallabor.contracts.enums import BlockStatus
from manuallabor.contracts.manifest import ManifestDocLearning, ManifestLearning
from manuallabor.export.load import last_models
from manuallabor.export.pipeline import summarize
from manuallabor.export.readme import FIG_REGEX
from manuallabor.export.types import MAX_ARTICLE_BYTES
from manuallabor.project import ProjectPaths
from tests.export.helpers import Exported
from tests.export.synth import bid, blk, flag, override, run, synth_inputs


def test_e18_readme_of_a_real_export(exported_a: Exported) -> None:
    text = exported_a.text("README.md")
    n = len([x for x in exported_a.names() if x.startswith("articles/") and x.endswith(".md")])
    assert f"{n} articles" in text
    assert FIG_REGEX in text and "How to ingest" in text
    assert re.search(r"A figure reference line matches the regex `\^!\\\[FIG-", text)
    assert "None: every exported block was auto-approved or approved by a human." in text
    assert "Review threshold: 0.85" in text and "cleanup: mock/" in text
    assert "2026-10-29T12:00:00Z" in text  # the injected clock is the only time in it
    assert "- `clean`: clean.pdf (sha256 " in text and "- `figures`: figures.pdf" in text
    assert "`clean`: grouping `baseline`, cleanup `baseline`" in text


def test_e18_readme_names_overrides_and_learning() -> None:
    inp = synth_inputs(
        [blk(1, "ok"), blk(2, "q", status=BlockStatus.queued)],
        flags=[flag(1, bid(2))],
        overrides=[override(3, "client waived")],
    )
    inp.learning = ManifestLearning(
        enabled=True, docs={"doc": ManifestDocLearning(group="001", clean="002")}
    )
    text = run(inp).readme
    assert "1 block(s) were exported without human approval" in text
    assert "Learning enabled: yes." in text and "grouping `001`, cleanup `002`" in text
    assert "None: every exported" not in text


def test_p8_a_large_article_is_not_split_but_warns() -> None:
    big = "word " * (MAX_ARTICLE_BYTES // 5 + 100)
    res = run(synth_inputs([blk(1, big), blk(2, "small")]))
    assert len(res.articles) == 1  # no splitting
    assert len(res.warnings) == 1 and "doc--main" in res.warnings[0]
    assert res.articles[0].text.count(big) == 1  # and no truncation


def test_summarize_warns_about_large_articles(tmp_path: Path) -> None:
    res = run(synth_inputs([blk(1, "x" * (MAX_ARTICLE_BYTES + 10))]))
    for name, src in res.files.items():
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src, encoding="utf-8") if isinstance(src, str) else None
    s = summarize(tmp_path, 123, "a" * 64, res.review)
    assert s.warnings and s.zip_bytes == 123 and s.articles == 1 and s.docs == 1
    assert s.pages_covered == 1 and s.review.approved == 1 and s.review.numbers_verified == 0
    assert s.review.blocks == 1 == s.review.total_blocks and s.review.left_out == {}


def test_the_models_in_the_manifest_are_the_last_logged_per_task(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    assert last_models(paths) == {}
    rows = [
        {"task": "cleanup", "provider": "ollama", "model": "a"},
        "not json",
        {"task": "bogus", "provider": "x", "model": "y"},
        {"task": "cleanup", "provider": "ollama", "model": "b"},
        {"task": "vision", "provider": "mock", "model": "m"},
        {"task": "grouping", "provider": "", "model": "m"},
    ]
    paths.llm_log.write_text(
        "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n\n",
        encoding="utf-8",
    )
    assert last_models(paths) == {"cleanup": ("ollama", "b"), "vision": ("mock", "m")}


def test_the_assembled_manifest_lists_the_configured_models_for_stage_tasks() -> None:
    m = run(synth_inputs([blk(1)])).manifest
    assert {t.value for t in m.models} == {"cleanup", "grouping", "embeddings", "vision"}
    inp = synth_inputs([blk(1)])
    inp.models = {"verifier": ("ollama", "qwen")}
    out = run(inp).manifest.models
    assert out[next(t for t in out if t.value == "verifier")].model == "qwen"
