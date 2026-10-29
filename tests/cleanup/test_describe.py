"""Tests 31-33: figure descriptions and the vision provider's json_schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from manuallabor.cleanup.describe import DESCRIBE_SCHEMA, describe_figure, describe_prompt
from manuallabor.cleanup.pipeline import run_clean
from manuallabor.contracts.enums import CallKind, Task
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json
from manuallabor.project import ProjectPaths
from manuallabor.providers import (
    ListSink,
    MockProvider,
    ProviderError,
    ProviderOutputError,
    ProviderSet,
)
from manuallabor.providers.base import RawChat
from manuallabor.providers.cache import LLMCache
from tests.cleanup.conftest import Proj, quiet


def _providers(sink: ListSink, cache: Path | None = None) -> ProviderSet:
    c = LLMCache(cache) if cache is not None else None
    return ProviderSet(by_task={t: MockProvider(sink=sink, cache=c) for t in Task})  # type: ignore[misc]


# -- 31 ------------------------------------------------------------------------------------


def test_31_mock_descriptions(cleanedproj: Proj) -> None:
    for slug in cleanedproj.paths.list_slugs():
        df = cleanedproj.describe(slug)
        for e in df.figures:
            p = cleanedproj.paths.figure_file(slug, e.figure_id, "json")
            if e.outcome == "skipped_failed":
                continue
            rec = read_json(p, FigureRecord)
            assert e.outcome == "ok", (slug, e.figure_id, e.outcome)
            png = (cleanedproj.paths.figure_dir(slug) / rec.file).resolve().read_bytes()
            sha = hashlib.sha256(png).hexdigest()
            assert e.image_sha256 == sha
            assert rec.description_generated == f"Generated description (mock) of image {sha[:8]}."
            assert rec.tags == ["figure", "mock"]


def test_31_duplicates_one_call_and_disabled(grouped_copy: ProjectPaths, tmp_path: Path) -> None:
    sink = ListSink()
    provs = _providers(sink, tmp_path / "cache")
    assert run_clean(grouped_copy, only="figures", emit=quiet, providers=provs) == []
    df = json.loads(grouped_copy.doc("figures").describe.read_text())
    shas = {e["image_sha256"] for e in df["figures"] if e["outcome"] == "ok"}
    vision = [x for x in sink if x.kind == CallKind.vision]
    assert len(vision) == len(shas) and all(not x.cached for x in vision)
    dup = {e["figure_id"]: e["image_sha256"] for e in df["figures"]}
    assert dup["FIG-figures-p006-01"] == dup["FIG-figures-p007-01"] == dup["FIG-figures-p002-01"]
    print(
        f"\nfigures.pdf: {len(df['figures'])} figures, {len(vision)} vision calls (distinct images)"
    )
    # disabled: no calls, descriptions cleared
    sink.clear()
    assert (
        run_clean(grouped_copy, only="figures", emit=quiet, providers=provs, describe=False) == []
    )
    assert [x for x in sink if x.kind == CallKind.vision] == []
    for e in json.loads(grouped_copy.doc("figures").describe.read_text())["figures"]:
        assert e["outcome"] == "skipped_disabled"
        rec = read_json(grouped_copy.figure_file("figures", e["figure_id"], "json"), FigureRecord)
        assert rec.description_generated is None and rec.tags == []


def test_31_out_of_scope_keeps_prior_ok(grouped_copy: ProjectPaths) -> None:
    from manuallabor.contracts.io import write_json
    from manuallabor.contracts.selection import Selection
    from manuallabor.grouping.selection import load_selection

    assert run_clean(grouped_copy, only="manual", emit=quiet) == []
    sel, _ = load_selection(grouped_copy)
    keep = [b for b in sel.block_ids if not b.startswith("b-manual-")]
    write_json(grouped_copy.selection, Selection(block_ids=keep))
    assert run_clean(grouped_copy, only="manual", emit=quiet) == []
    df = json.loads(grouped_copy.doc("manual").describe.read_text())
    assert {e["outcome"] for e in df["figures"]} == {"ok"}  # prior ok entries survive
    att = json.loads(grouped_copy.doc("manual").attach.read_text())
    assert att["articles"] == [] and {u["reason"] for u in att["unattached"]} == {"not_selected"}


# -- 32 VLM replies -------------------------------------------------------------------------

GOOD = json.dumps({"description": "A pump with two bolts.", "tags": ["pump", "bolts"]})


@pytest.mark.parametrize(
    "bad",
    [
        "A pump with two bolts.",
        json.dumps({"description": "A pump.", "tags": [], "extra": 1}),
        json.dumps({"description": "x" * 301, "tags": []}),
        json.dumps({"description": "A pump.", "tags": [f"t{i}" for i in range(9)]}),
        json.dumps({"description": "A pump.", "tags": ["Pump"]}),
        json.dumps({"description": "   ", "tags": []}),
        json.dumps({"description": "A\u0007pump", "tags": []}),
    ],
)
def test_32_invalid_replies_retry_once(bad: str) -> None:
    prompts: list[str] = []

    def reply(img: bytes, prompt: str) -> str:
        prompts.append(prompt)
        return bad

    sink = ListSink()
    d = describe_figure(MockProvider(sink=sink, vision_response=reply), b"png", "Figure 1. Pump.")
    assert d.outcome == "invalid" and d.description is None and d.tags == [] and d.calls == 2
    assert len(prompts) == 2 and prompts[0] != prompts[1] and "rejected" in prompts[1]
    assert sink[0].input_hash != sink[1].input_hash


def test_32_valid_after_retry_and_errors() -> None:
    replies = iter(["not json", GOOD])
    d = describe_figure(
        MockProvider(sink=ListSink(), vision_response=lambda b, p: next(replies)), b"png", None
    )
    assert (
        d.outcome == "ok"
        and d.description == "A pump with two bolts."
        and d.tags == ["pump", "bolts"]
    )

    class Down(MockProvider):
        def _vision_raw(self, *a: Any, **k: Any) -> RawChat:
            raise ProviderError("no eyes")

    d = describe_figure(Down(sink=ListSink()), b"png", None)
    assert d.outcome == "error" and d.calls == 1


def test_32_prompt() -> None:
    p = describe_prompt("Figure 1.  Pump\nhousing.")
    assert p.startswith("desc-v1") and "Figure 1. Pump housing." in p


# -- 33 provider json_schema ----------------------------------------------------------------


def test_33_vision_schema(tmp_path: Path) -> None:
    sink = ListSink()
    cache = LLMCache(tmp_path / "c")
    p = MockProvider(sink=sink, cache=cache)
    r = p.vision(Task.vision, b"img", "describe", json_schema=DESCRIBE_SCHEMA)
    sha8 = hashlib.sha256(b"img").hexdigest()[:8]
    assert r.parsed == {
        "description": f"Generated description (mock) of image {sha8}.",
        "tags": ["figure", "mock"],
    }
    assert len(sink) == 1 and not sink[0].cached
    p.vision(Task.vision, b"img", "describe", json_schema=DESCRIBE_SCHEMA)
    assert sink[1].cached
    # without a schema: the pre-schema cache key and the legacy reply
    legacy = p.vision(Task.vision, b"img", "describe")
    assert legacy.parsed is None and legacy.text.startswith("Generated description (mock)")
    key = LLMCache.key(
        p.cache_namespace, Task.vision, CallKind.vision,
        {"image_sha256": hashlib.sha256(b"img").hexdigest(), "prompt": "describe"},
    )  # fmt: skip
    assert sink[-1].input_hash == key and sink[-1].input_hash != sink[0].input_hash
    # a failing reply is never cached and is logged once
    bad = MockProvider(sink=sink, cache=cache, vision_response=lambda b, pr: "nope")
    n = len(sink)
    for _ in range(2):
        with pytest.raises(ProviderOutputError):
            bad.vision(Task.vision, b"img", "describe", json_schema=DESCRIBE_SCHEMA)
    assert len(sink) == n + 2 and not sink[-1].ok and not sink[-1].cached
