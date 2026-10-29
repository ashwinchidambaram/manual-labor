from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from manuallabor import contracts as c
from manuallabor.cli import app
from manuallabor.contracts.io import dump_json, read_json, write_json
from manuallabor.contracts.schema_export import export_schemas
from tests.contracts.factories import (
    SLUG,
    TS,
    block_dict,
    document_dict,
    figure_dict,
    manifest_dict,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "SPEC.md").read_text(encoding="utf-8")


def _spec_figure() -> dict[str, Any]:
    start = SPEC.index("### 6.3")
    start = SPEC.index("```json\n", start) + len("```json\n")
    raw = SPEC[start : SPEC.index("```", start)].replace("c3a1\u2026", "c3a1b2c3d4e5f607")
    return json.loads(raw)  # type: ignore[no-any-return]


SPEC_FIGURE = _spec_figure()


def _spec_frontmatter() -> str:
    start = SPEC.index("```markdown\n---\n") + len("```markdown\n---\n")
    return SPEC[start : SPEC.index("\n---\n", start)]


def bad(model: type[BaseModel], data: dict[str, Any], match: str | None = None) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(data)


def test_c1_figure_spec_example() -> None:
    # sanity: literal example in the spec is the one we replicate (phash elided there)
    assert '"id": "FIG-acme-x200-service-p042-01"' in SPEC
    m = c.FigureRecord.model_validate(SPEC_FIGURE)
    assert m.model_dump(mode="json") == SPEC_FIGURE
    assert list(m.model_dump()) == list(SPEC_FIGURE)


def test_c2_frontmatter_spec_example() -> None:
    data = yaml.safe_load(_spec_frontmatter())
    data["generated_at"] = data["generated_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
    m = c.ArticleFrontmatter.model_validate(data)
    assert m.model_dump(mode="json") == data
    assert list(c.ArticleFrontmatter.model_fields) == list(
        yaml.safe_load(_spec_frontmatter()).keys()
    )
    assert list(m.to_yaml_dict()) == list(data)


@pytest.mark.parametrize("model", c.EXPORTED_MODELS, ids=lambda m: m.__name__)
def test_c3_extra_forbidden(model: type[BaseModel]) -> None:
    assert model.model_config["extra"] == "forbid"
    samples: dict[str, dict[str, Any]] = {
        "Block": block_dict(),
        "Document": document_dict(),
        "FigureRecord": figure_dict(),
        "Group": {
            "id": f"g-{SLUG}-t001",
            "view": "topic",
            "doc_id": SLUG,
            "title": "T",
            "slug": "t",
            "block_ids": [],
            "page_ranges": [],
            "block_count": 0,
            "figure_count": 0,
        },
        "Selection": {"block_ids": []},
        "GroupsFile": {
            "doc_id": SLUG,
            "algo_version": "1",
            "fingerprint": "d" * 64,
            "embedding_model": "mock:mock-1",
            "embedding_dim": 0,
            "grouping_model": "mock:mock-1",
            "learning_snapshot": "baseline",
            "params": {
                "summary_tokens": 64,
                "name_sample": 12,
                "name_tokens": 40,
                "embed_batch": 32,
                "embed_prefix": "",
                "small_doc": 12,
                "d_cut": 0.8,
                "k_max_divisor": 4,
                "min_topic_blocks": 3,
                "max_topic_blocks": 60,
                "t_assign": 0.3,
                "t_candidate": 0.15,
                "n_candidates": 3,
                "straggler_batch": 10,
                "low_cohesion": 0.3,
                "page_window": 10,
                "title_max": 80,
                "topic_slug_max": 40,
                "llm_stragglers": True,
            },
            "structure": [],
            "topics": [],
            "unassigned": [],
            "stragglers": [],
            "overlap": [],
            "title_sources": {},
            "topic_status": "ok",
            "topic_error": None,
            "overrides_applied": 0,
            "overrides_stale": [],
        },
        "CoverageReport": {
            "doc_id": SLUG,
            "selected": 0,
            "selectable": 0,
            "structure": [],
            "topics": [],
        },
        "ScopeSummary": {
            "docs": 0,
            "articles_per_topic": 0,
            "articles_per_document": 0,
            "articles": 0,
            "blocks": 0,
            "figures": 0,
            "pages": 0,
            "review_load": {"queued": 0, "numeric_queued": 0, "threshold": 0.85},
        },
        "Flag": {
            "id": "flag-000001",
            "target_id": f"b-{SLUG}-p001-01",
            "category": "wrong_text",
            "created_at": TS,
        },
        "Decision": {
            "seq": 1,
            "block_id": f"b-{SLUG}-p001-01",
            "action": "approve",
            "score": 0.9,
            "threshold": 0.85,
            "signals": [],
            "timestamp": TS,
        },
        "Proposal": {
            "id": "prop-000001",
            "flag_id": "flag-000001",
            "target_id": f"b-{SLUG}-p001-01",
            "proposal_text": "x",
            "evidence": ["pymupdf"],
            "rationale": "r",
            "model": "mock/mock-1",
            "input_hash": "b" * 64,
            "created_at": TS,
        },
        "ArticleFrontmatter": {
            "id": SLUG,
            "title": "T",
            "source_doc": SLUG,
            "source_file": "a.pdf",
            "product_model": None,
            "pages": [1],
            "sections": [],
            "figures": [],
            "blocks": 1,
            "review": {"approved": 1, "edited": 0, "overrides": 0},
            "generated_at": TS,
        },
        "Manifest": manifest_dict(),
        "ProjectConfig": {"name": "x"},
        "ProbeResult": {
            "probed_at": TS,
            "platform": {"system": "Darwin", "machine": "arm64"},
            "cpu": {"model": "Apple M3", "cores_physical": 8, "cores_logical": 8},
            "ram_gb": 16.0,
            "gpu": {"vendor": "apple", "name": "Apple M3", "vram_gb": None, "unified": True},
            "effective_model_memory_gb": 10.6,
            "disk_free_gb": 8.5,
            "disk_path": "/tmp",
            "ollama": {
                "installed": True,
                "version": "0.40.2",
                "host": "http://localhost:11434",
                "reachable": True,
                "models": [{"name": "llama3.2:1b", "size_gb": 1.3, "digest": "baf6a787fdff"}],
            },
            "litellm_version": "1.106.5",
            "notes": [],
        },
        "SuggestionTable": {
            "default_tier": "small",
            "rows": [
                {
                    "task": "cleanup",
                    "small": {
                        "provider": "ollama",
                        "model": "m",
                        "approx_gb": 1.3,
                        "fits": True,
                        "speed_class": "fast",
                        "est_tokens_per_s": 38.5,
                        "pull_command": None,
                        "present": True,
                    },
                    "medium": {
                        "provider": "ollama",
                        "model": "m",
                        "approx_gb": 1.3,
                        "fits": True,
                        "speed_class": "fast",
                        "est_tokens_per_s": 38.5,
                        "pull_command": None,
                        "present": True,
                    },
                    "large": {
                        "provider": "ollama",
                        "model": "m",
                        "approx_gb": 1.3,
                        "fits": True,
                        "speed_class": "fast",
                        "est_tokens_per_s": 38.5,
                        "pull_command": None,
                        "present": True,
                    },
                    "api": {
                        "provider": "ollama",
                        "model": "m",
                        "approx_gb": 1.3,
                        "fits": True,
                        "speed_class": "fast",
                        "est_tokens_per_s": 38.5,
                        "pull_command": None,
                        "present": True,
                    },
                }
            ],
            "pull_commands": {},
        },
        "LLMCallLog": {
            "task": "cleanup",
            "kind": "chat",
            "provider": "mock",
            "model": "m",
            "input_hash": "c" * 64,
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1.5,
            "cached": False,
            "timestamp": TS,
        },
    }
    data = samples[model.__name__]
    model.model_validate(data)
    bad(model, {**data, "bogus": 1}, "bogus")


def test_c4_bbox() -> None:
    for b in ([0, 0, 1], [0, 0, 1, 1, 1], [5, 0, 1, 1], [math.nan, 0, 1, 1], [0, 0, math.inf, 1]):
        bad(c.Block, block_dict(bbox=b))
    blk = c.Block.model_validate(block_dict(bbox=[1.23456789, -0.0, 2, 3]))
    assert blk.bbox == [1.234568, 0.0, 2.0, 3.0]
    assert "-0.0" not in dump_json(blk)
    assert math.copysign(1.0, blk.bbox[1]) == 1.0  # type: ignore[index]


def test_c5_unit() -> None:
    for v in (-0.01, 1.0000001, math.nan):
        bad(c.Signal, {"name": "ocr_mean", "value": v, "critical": False})
    for v in (0, 1):
        assert c.Signal(name=c.SignalName.ocr_mean, value=v, critical=False).value == v
    assert c.Signal(name=c.SignalName.ocr_mean, value=0.12345678, critical=False).value == 0.123457


def test_c6_block_validators() -> None:
    c.Block.model_validate(block_dict())
    bad(c.Block, block_dict(doc_id="other"), "slug/page")
    bad(c.Block, block_dict(page=41), "slug/page")
    bad(c.Block, block_dict(id="nonsense"))
    bad(c.Block, block_dict(heading_level=2), "heading_level")
    c.Block.model_validate(block_dict(type="heading", heading_level=2))
    table = {
        "n_rows": 1,
        "n_cols": 1,
        "cells": [{"row": 0, "col": 0, "text": "a"}],
        "markdown": "| a |",
    }
    bad(c.Block, block_dict(table=table), "table")
    c.Block.model_validate(block_dict(type="table", table=table))
    fid = f"FIG-{SLUG}-p042-01"
    bad(c.Block, block_dict(type="figure"), "figure_id")
    bad(c.Block, block_dict(figure_id=fid), "figure_id")
    bad(c.Block, block_dict(type="figure", figure_id=f"FIG-{SLUG}-p043-01"), "figure_id")
    c.Block.model_validate(block_dict(type="figure", figure_id=fid))
    bad(c.Block, block_dict(status="edited"), "clean_text")
    c.Block.model_validate(block_dict(status="edited", clean_text="x"))
    sigs = [
        {"name": "ocr_min", "value": 0.5, "critical": False},
        {"name": "faithfulness", "value": 1.0, "critical": True},
    ]
    blk = c.Block.model_validate(block_dict(signals=sigs))
    assert [s["name"] for s in blk.model_dump(mode="json")["signals"]] == [
        "faithfulness",
        "ocr_min",
    ]
    bad(c.Block, block_dict(signals=[sigs[0], sigs[0]]), "unique")
    bad(c.Block, block_dict(section_number="5.x"))


def test_c6_table_and_faithfulness() -> None:
    cell = {"row": 0, "col": 0, "text": "a"}
    base = {"n_rows": 2, "n_cols": 2, "markdown": ""}
    bad(c.TableData, {**base, "cells": [{**cell, "row": 1}, cell]})
    bad(c.TableData, {**base, "cells": [cell, cell]})
    bad(c.TableData, {**base, "cells": [{**cell, "row_span": 3}]})
    bad(c.TableData, {**base, "cells": [{**cell, "col_span": 3}]})
    ok = {"passed": True, "alignment_ratio": 1.0, "violations": [], "diff": []}
    c.FaithfulnessResult.model_validate(ok)
    bad(c.FaithfulnessResult, {**ok, "passed": False})
    v = {
        "kind": "insertion",
        "raw_start": None,
        "raw_end": None,
        "clean_start": 0,
        "clean_end": 1,
        "raw": "",
        "clean": "x",
    }
    bad(c.FaithfulnessResult, {**ok, "violations": [v]})
    c.FaithfulnessResult.model_validate({**ok, "passed": False, "violations": [v]})


def test_c7_document() -> None:
    c.Document.model_validate(document_dict())
    bad(c.Document, document_dict(sha256="xyz"))
    bad(c.Document, document_dict(product_model_inferred=True), "product_model")
    bad(c.Document, document_dict(slug="Bad_Slug"))
    bad(c.Document, document_dict(kind="docx", pages_without_text_layer=[1]), "docx")
    bad(c.Document, document_dict(pages_without_text_layer=[200]), "page_count")
    bad(c.Document, document_dict(pages_without_text_layer=[3, 2]))


def test_c8_figure() -> None:
    fid = f"FIG-{SLUG}-p042-01"
    c.FigureRecord.model_validate(figure_dict())
    bad(c.FigureRecord, figure_dict(extraction="vector"), "svg")
    bad(c.FigureRecord, figure_dict(extraction="crop", svg=f"{fid}.svg"), "svg")
    c.FigureRecord.model_validate(figure_dict(extraction="vector", svg=f"{fid}.svg"))
    bad(c.FigureRecord, figure_dict(extraction="vector", svg="other.svg"), "svg")
    bad(c.FigureRecord, figure_dict(source_doc="other-doc"), "source_doc")
    bad(c.FigureRecord, figure_dict(page=43), "source_doc")
    bad(c.FigureRecord, figure_dict(phash="XYZ"))
    bad(c.FigureRecord, figure_dict(file="foo.png"), "file")
    bad(c.FigureRecord, figure_dict(file=f"{fid}.gif"), "file")
    ok = c.FigureRecord.model_validate(figure_dict(file="../other-doc/FIG-other-doc-p001-01.png"))
    assert ok.file.startswith("../other-doc/")
    t = c.FigureRecord.model_validate(figure_dict(tags=["B", "a", "b"]))
    assert t.tags == ["b", "a"]


def test_c9_decision() -> None:
    d: dict[str, Any] = {
        "seq": 1,
        "block_id": f"b-{SLUG}-p001-01",
        "action": "approve",
        "score": None,
        "threshold": 0.85,
        "signals": [],
        "timestamp": TS,
    }
    c.Decision.model_validate(d)
    bad(c.Decision, {**d, "action": "edit"}, "edited_text")
    bad(c.Decision, {**d, "edited_text": "x"}, "edited_text")
    bad(c.Decision, {**d, "action": "flag"}, "flag_id")
    c.Decision.model_validate({**d, "action": "flag", "flag_id": "flag-000001"})
    c.Decision.model_validate({**d, "action": "edit", "edited_text": "x"})


def _proposal(**over: Any) -> dict[str, Any]:
    d = {
        "id": "prop-000001",
        "flag_id": "flag-000001",
        "target_id": f"b-{SLUG}-p001-01",
        "proposal_text": "x",
        "evidence": ["pymupdf"],
        "rationale": "one line",
        "model": "mock/mock-1",
        "input_hash": "b" * 64,
        "created_at": TS,
    }
    d.update(over)
    return d


def test_c10_proposal() -> None:
    from manuallabor.contracts.proposal import REQUIRED_CHECKS

    full = [{"check": x, "passed": True} for x in REQUIRED_CHECKS[c.ProposalKind.text]]
    p = c.Proposal.model_validate(_proposal(rechecks=full))
    dumped = p.model_dump(mode="json")
    assert dumped["all_checks_passed"] is True
    # an incomplete check list never passes (module 10 review fix)
    part = c.Proposal.model_validate(_proposal(rechecks=[{"check": "z", "passed": True}]))
    assert part.model_dump(mode="json")["all_checks_passed"] is False
    assert c.Proposal.model_validate(dumped) == p  # round trip with computed field
    p2 = c.Proposal.model_validate(
        _proposal(rechecks=[{"check": "b", "passed": False}, {"check": "a", "passed": True}])
    )
    assert [r.check for r in p2.rechecks] == ["a", "b"]
    assert p2.model_dump(mode="json")["all_checks_passed"] is False
    bad(c.Proposal, _proposal(rationale="a\nb"), "single line")
    bad(c.Proposal, _proposal(proposed_bbox=[0, 0, 1, 1]), "exactly one")
    bad(c.Proposal, _proposal(proposal_text=None), "exactly one")
    bad(c.Proposal, _proposal(status="edited"), "final_text")
    bad(c.Proposal, _proposal(round=2), "history")
    bad(c.Proposal, _proposal(evidence=[]))
    bad(c.Proposal, _proposal(rationale="x" * 301))
    c.Proposal.model_validate(_proposal(proposal_text=None, proposed_bbox=[0, 0, 1, 1]))


def test_c11_selection() -> None:
    a, b, d = (f"b-{SLUG}-p{p:03d}-01" for p in (9, 10, 2))
    s1 = c.Selection.model_validate({"block_ids": [b, a, a, d]})
    s2 = c.Selection.model_validate({"block_ids": [d, a, b]})
    assert dump_json(s1) == dump_json(s2)
    assert s1.block_ids == [d, a, b]  # p010 sorts after p009 (and p002 first)


def test_c12_manifest() -> None:
    base = manifest_dict()
    c.Manifest.model_validate(base)
    b1, b2, b3 = (f"b-{SLUG}-p001-0{i}" for i in (1, 2, 3))

    def mut(fn: Any) -> dict[str, Any]:
        d = deepcopy(base)
        fn(d)
        return d

    # block in two articles
    def two(d: dict[str, Any]) -> None:
        d["articles"].append(
            {**d["articles"][0], "id": f"{SLUG}--x", "path": f"articles/{SLUG}--x.md"}
        )

    bad(c.Manifest, mut(two), "block_ids")
    # missing block
    bad(c.Manifest, mut(lambda d: d["accounting"]["assignments"].pop(b3)), "total_blocks")
    # article block absent from assignments
    bad(
        c.Manifest,
        mut(lambda d: d["articles"][0]["block_ids"].append(b3)),
        "block_ids",
    )
    # unknown target
    bad(
        c.Manifest,
        mut(lambda d: d["accounting"]["assignments"].update({b3: "ghost"})),
        "unknown article",
    )
    # unassigned without reason
    bad(c.Manifest, mut(lambda d: d["accounting"]["unassigned_reasons"].clear()), "unassigned")
    # total mismatch with review stats
    bad(c.Manifest, mut(lambda d: d["review_stats"].update(total_blocks=4)), "total_blocks")
    # unknown figure
    bad(
        c.Manifest,
        mut(lambda d: d["articles"][0]["figures"].append(f"FIG-{SLUG}-p001-02")),
        "figure",
    )

    # duplicate_of chains
    def dup(d: dict[str, Any]) -> None:
        f = d["figures"][0]
        d["figures"].append(
            {
                **f,
                "id": f"FIG-{SLUG}-p001-02",
                "sidecar": f"images/{SLUG}/FIG-{SLUG}-p001-02.json",
                "duplicate_of": f["id"],
            }
        )
        d["figures"][0]["duplicate_of"] = f"FIG-{SLUG}-p001-02"

    bad(c.Manifest, mut(dup), "duplicate_of")
    # sorted on dump
    m = c.Manifest.model_validate(base)
    assert m.schema_version == "1.0"


def test_c13_config() -> None:
    cfg = c.ProjectConfig(name="x")
    assert cfg.threshold == 0.85
    assert cfg.article_split == c.ArticleSplit.per_topic
    assert cfg.parsers == ["pymupdf", "docling"]
    assert cfg.ocr_engine == c.OcrEngine.auto
    assert cfg.ocr_dpi == 300
    assert cfg.target_edit_rate == 0.02
    assert cfg.models.cleanup.model == "llama3.2:1b"
    assert cfg.models.vision.model == "moondream"
    assert cfg.models.verifier is not None and cfg.models.verifier.model == "qwen2.5:1.5b"
    assert cfg.models.embeddings.model == "nomic-embed-text"
    bad(c.ProjectConfig, {"name": "x", "parsers": ["pymupdf"]})
    bad(c.ProjectConfig, {"name": "x", "parsers": ["a", "a"]})
    bad(c.ProjectConfig, {"name": "x", "ocr_dpi": 200})
    assert cfg.model_for(c.Task.metadata) == cfg.models.grouping
    assert cfg.model_for(c.Task.agent) == cfg.models.cleanup
    cfg2 = c.ProjectConfig.model_validate({"name": "x", "models": {"verifier": None}})
    assert cfg2.model_for(c.Task.verifier) is None
    assert cfg.model_for(c.Task.vision) == cfg.models.vision
    ref = c.ModelRef(provider="mock", model="m")
    cfg3 = cfg.model_copy(update={"models": cfg.models.model_copy(update={"agent": ref})})
    assert cfg3.model_for(c.Task.agent) == ref
    bad(c.ModelRef, {"provider": "Bad-Name", "model": "m"})


def test_c14_datetime() -> None:
    def flag(ts: Any) -> c.Flag:
        return c.Flag.model_validate(
            {
                "id": "flag-000001",
                "target_id": f"b-{SLUG}-p001-01",
                "category": "wrong_text",
                "created_at": ts,
            }
        )

    with pytest.raises(ValidationError):
        flag("2026-01-01T00:00:00")
    assert flag("2026-01-01T02:00:00+02:00").model_dump(mode="json")["created_at"] == (
        "2026-01-01T00:00:00Z"
    )
    assert flag("2026-01-01T00:00:00.123456Z").model_dump(mode="json")["created_at"] == (
        "2026-01-01T00:00:00.123Z"
    )
    assert flag("2026-01-01T00:00:00.000Z").model_dump(mode="json")["created_at"] == (
        "2026-01-01T00:00:00Z"
    )
    assert flag("2026-10-28T18:00:00Z").target_kind == "block"


def test_c14b_flag_validators() -> None:
    d = {
        "id": "flag-000001",
        "target_id": f"FIG-{SLUG}-p001-01",
        "category": "bad_crop",
        "created_at": TS,
    }
    assert c.Flag.model_validate(d).target_kind == "figure"
    assert "target_kind" not in c.Flag.model_validate(d).model_dump()
    bad(c.Flag, {**d, "status": "resolved"}, "resolved_at")
    bad(c.Flag, {**d, "resolved_at": TS}, "resolved_at")
    bad(c.Flag, {**d, "target_id": "junk"})


def test_c15_dump_json(tmp_path: Path) -> None:
    d1 = block_dict()
    d2 = dict(reversed(list(d1.items())))
    s1, s2 = dump_json(c.Block.model_validate(d1)), dump_json(c.Block.model_validate(d2))
    assert s1 == s2 and s1.endswith("\n")
    assert "N·m" in s1 and "\\u00b7" not in s1
    p = tmp_path / "sub" / "b.json"
    write_json(p, c.Block.model_validate(d1))
    assert p.read_text(encoding="utf-8") == s1
    assert list(p.parent.glob("*.tmp")) == []
    assert read_json(p, c.Block) == c.Block.model_validate(d1)


def test_c16_schema_export(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    export_schemas(a)
    export_schemas(b)
    names = {p.name for p in a.iterdir()}
    assert names == {f"{m.__name__}.json" for m in c.EXPORTED_MODELS} | {"_all.json"}
    for n in names:
        assert (a / n).read_bytes() == (b / n).read_bytes()
    assert export_schemas(a, check=True) == []
    runner = CliRunner()
    r = runner.invoke(app, ["schemas", "export", "--out", str(a), "--check"])
    assert r.exit_code == 0
    with open(a / "Block.json", "a", encoding="utf-8") as f:
        f.write(" ")
    r = runner.invoke(app, ["schemas", "export", "--out", str(a), "--check"])
    assert r.exit_code == 1
    assert (a / "Block.json").read_text().endswith(" ")  # check wrote nothing
    export_schemas(a)
    assert export_schemas(a, check=True) == []
    (a / "Stale.json").write_text("{}")
    r = runner.invoke(app, ["schemas", "export", "--out", str(a), "--check"])
    assert r.exit_code == 1
    assert (a / "Stale.json").exists()
    export_schemas(a)
    assert not (a / "Stale.json").exists()


def test_c16b_committed_schemas_current() -> None:
    assert export_schemas(ROOT / "schemas", check=True) == []


def test_c17_schemas_valid() -> None:
    sdir = ROOT / "schemas"
    for p in sdir.glob("*.json"):
        Draft202012Validator.check_schema(json.loads(p.read_text(encoding="utf-8")))
    fig = json.loads((sdir / "FigureRecord.json").read_text(encoding="utf-8"))
    Draft202012Validator(fig).validate(SPEC_FIGURE)
    fm = yaml.safe_load(_spec_frontmatter())
    fm["generated_at"] = fm["generated_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
    art = json.loads((sdir / "ArticleFrontmatter.json").read_text(encoding="utf-8"))
    Draft202012Validator(art).validate(fm)
    prop = json.loads((sdir / "Proposal.json").read_text(encoding="utf-8"))
    dumped = c.Proposal.model_validate(_proposal()).model_dump(mode="json")
    Draft202012Validator(prop).validate(dumped)


def test_c18_enums() -> None:
    assert [e.value for e in c.BlockType] == [
        "heading",
        "paragraph",
        "list",
        "table",
        "figure",
        "caption",
        "header",
        "footer",
        "other",
    ]
    assert [e.value for e in c.BlockStatus] == [
        "auto_approved",
        "queued",
        "approved",
        "edited",
        "flagged",
        "rejected",
    ]
    assert [e.value for e in c.FlagCategory] == [
        "wrong_text",
        "missing_figure",
        "wrong_grouping",
        "bad_crop",
        "table_structure",
    ]
    assert [e.value for e in c.Extraction] == ["native", "vector", "crop"]
    assert [e.value for e in c.AttachRule] == [
        "caption_ref",
        "caption_match",
        "proximity",
        "none",
        "human",
    ]
    assert len(c.SignalName) == 13 and len(c.Task) == 7


def test_group_validators() -> None:
    g: dict[str, Any] = {
        "id": f"g-{SLUG}-s001",
        "view": "structure",
        "doc_id": SLUG,
        "title": "T",
        "slug": "t",
        "block_ids": [f"b-{SLUG}-p001-01"],
        "page_ranges": [{"start": 1, "end": 2}],
        "block_count": 1,
        "figure_count": 0,
    }
    c.Group.model_validate(g)
    bad(c.Group, {**g, "block_count": 2}, "block_count")
    bad(c.Group, {**g, "view": "topic"}, "view")
    bad(c.Group, {**g, "is_unassigned": True}, "is_unassigned")
    bad(c.Group, {**g, "block_ids": ["b-other-p001-01"]}, "doc_id")
    bad(c.Group, {**g, "page_ranges": [{"start": 3, "end": 2}]}, "end")
    bad(
        c.Group,
        {**g, "page_ranges": [{"start": 1, "end": 3}, {"start": 2, "end": 4}]},
        "page_ranges",
    )
    t = {**g, "id": f"g-{SLUG}-t000", "view": "topic", "slug": "unassigned", "is_unassigned": True}
    c.Group.model_validate(t)
    bad(c.Group, {**t, "parent_id": f"g-{SLUG}-s001"}, "parent_id")


def test_misc_models() -> None:
    log = {
        "task": "cleanup",
        "kind": "chat",
        "provider": "p",
        "model": "m",
        "input_hash": "c" * 64,
        "prompt_tokens": None,
        "completion_tokens": None,
        "latency_ms": 1.23456,
        "cached": True,
        "timestamp": TS,
    }
    assert c.LLMCallLog.model_validate(log).latency_ms == 1.235
    bad(c.LLMCallLog, {**log, "latency_ms": -1})
    rc = {"approved": 1, "edited": 2, "overrides": 0}
    bad(c.ReviewCounts, rc, "edited")
    bad(
        c.ArticleFrontmatter,
        {
            "id": SLUG,
            "title": "T",
            "source_doc": SLUG,
            "source_file": "a",
            "product_model": None,
            "pages": [2, 1],
            "sections": [],
            "figures": [],
            "blocks": 1,
            "review": {"approved": 1, "edited": 0, "overrides": 0},
            "generated_at": TS,
        },
        "pages",
    )
    bad(
        c.ArticleFrontmatter,
        {
            "id": SLUG,
            "title": "T",
            "source_doc": SLUG,
            "source_file": "a",
            "product_model": None,
            "pages": [1],
            "sections": [],
            "figures": [],
            "blocks": 0,
            "review": {"approved": 1, "edited": 0, "overrides": 0},
            "generated_at": TS,
        },
        "blocks",
    )


def test_c12b_manifest_source_doc_cross_checks() -> None:
    """Re-review finding: article/figure source_doc must match the id slug."""
    base = manifest_dict()
    c.Manifest.model_validate(base)

    def mut(fn: Any) -> dict[str, Any]:
        d = deepcopy(base)
        fn(d)
        return d

    def other_doc(d: dict[str, Any]) -> None:
        d["docs"].append({**deepcopy(d["docs"][0]), "slug": "other", "block_ids": []})

    # article whose id/slug and source_doc disagree, holding another doc's blocks
    def art_other(d: dict[str, Any]) -> None:
        other_doc(d)
        d["articles"][0]["source_doc"] = "other"

    bad(c.Manifest, mut(art_other), "source_doc")

    # figure whose id slug differs from source_doc (direct sub-model check)
    bad(
        c.ManifestFigure,
        {
            "id": f"FIG-{SLUG}-p001-01",
            "sidecar": f"images/other/FIG-{SLUG}-p001-01.json",
            "file": f"images/other/FIG-{SLUG}-p001-01.png",
            "source_doc": "other",
        },
        "source_doc",
    )
