"""T11: live cleanup smoke through the real Ollama provider (module 5 verify chain).

Runs only with MANUALLABOR_LIVE=1 and the small-tier chat model pulled. Never run beside another
Docling/LLM process (16 GB)."""

from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter
from pathlib import Path

import pytest

from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.types import LLM_TYPES
from manuallabor.contracts import ModelRef
from manuallabor.providers import JsonlSink, LLMCache
from manuallabor.providers.base import utc_now
from manuallabor.providers.registry import make_factory
from tests.cleanup.conftest import groupedproj  # noqa: F401  (session fixture)
from tests.cleanup.test_gt import independent_check

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if "://" not in OLLAMA:
    OLLAMA = "http://" + OLLAMA
MODEL = "llama3.2:1b"
LIMIT = 10


def _ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA.rstrip('/')}/api/tags", timeout=3) as r:  # noqa: S310
            names = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return False
    return MODEL in names


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MANUALLABOR_LIVE") != "1" or not _ready(),
        reason=f"set MANUALLABOR_LIVE=1 and run yourself: ollama pull {MODEL}",
    ),
]


def test_t11_live_cleanup_smoke(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    proj = request.getfixturevalue("groupedproj")
    slug = "clean"
    calls = tmp_path / "llm_calls.jsonl"
    cache = LLMCache(tmp_path / ".llm_cache")
    prov = make_factory("ollama")(
        ModelRef(provider="ollama", model=MODEL), JsonlSink(calls), cache, utc_now
    )
    raw = proj.raw_blocks(slug)
    eligible = [
        b
        for b in sorted(raw, key=lambda b: b.reading_order)
        if b.type in LLM_TYPES and b.raw_text.strip()
    ][:LIMIT]
    assert len(eligible) == LIMIT

    def run() -> list:  # type: ignore[type-arg]
        entries, _ = clean_document(
            proj.doc(slug),
            raw,
            proj.layouts(slug),
            {b.id for b in eligible},
            mode="always",
            provider=prov,
            cleanup_ref=f"ollama:{MODEL}",
        )
        return entries

    entries = run()
    ctxs = proj.contexts(slug)
    by_id = {b.id: b for b in raw}
    outcomes: Counter[str] = Counter()
    reaching = 0
    attempted = rejected = 0
    for e in entries:
        assert e.llm is not None
        attempted += 1
        if e.llm.outcome == "rejected":
            rejected += 1
        outcomes[e.llm.outcome if e.llm.outcome != "rejected" else f"rejected:{e.llm.reason}"] += 1
        b = by_id[e.block_id].model_copy(update={"clean_text": e.clean_text})
        reaching += len(independent_check(b, ctxs[b.id]))
    print(
        f"\nLIVE T11 {MODEL}: LLM attempted={attempted} rejected={rejected} "
        f"violations reaching clean_text={reaching} outcomes={dict(sorted(outcomes.items()))}"
    )
    assert reaching == 0
    rows = [json.loads(line) for line in calls.read_text().splitlines()]
    assert any(r["provider"] == "ollama" for r in rows)
    first_n = len(rows)
    # second run: every call is a cache hit (no model request is made)
    run()
    rows2 = [json.loads(line) for line in calls.read_text().splitlines()][first_n:]
    assert rows2 and all(r["cached"] for r in rows2)
