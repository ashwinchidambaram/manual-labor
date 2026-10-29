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
from manuallabor.contracts import ModelRef, TaskModels
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


VERIFIER_MODEL = TaskModels().verifier.model  # type: ignore[union-attr]


def _missing() -> list[str]:
    """`ollama pull` lines for the models T11 needs and Ollama does not have."""
    try:
        with urllib.request.urlopen(f"{OLLAMA.rstrip('/')}/api/tags", timeout=3) as r:  # noqa: S310
            names = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception:
        return ["(Ollama is not reachable: start it with `ollama serve`)"]
    have = names | {n.removesuffix(":latest") for n in names}
    return [f"ollama pull {m}" for m in (MODEL, VERIFIER_MODEL) if m not in have]


_LIVE = os.environ.get("MANUALLABOR_LIVE") == "1"
_MISSING = _missing() if _LIVE else []
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE or bool(_MISSING),
        reason=(
            "set MANUALLABOR_LIVE=1 to run"
            if not _LIVE
            else "missing for T11, run yourself:\n  " + "\n  ".join(_MISSING)
        ),
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
    _assert_verifier_signal(proj, slug, entries, by_id, ctxs, tmp_path)
    first_n = len(rows)
    # second run: every call is a cache hit (no model request is made)
    run()
    rows2 = [json.loads(line) for line in calls.read_text().splitlines()][first_n:]
    # failures (truncated or errored replies) are never cached, so only they may be re-asked
    failed = {r["input_hash"] for r in rows if not r["ok"]}
    assert rows2 and all(r["cached"] or r["input_hash"] in failed for r in rows2)
    assert any(r["cached"] for r in rows2)


def _assert_verifier_signal(proj, slug, entries, by_id, ctxs, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The default config's verifier (qwen2.5:1.5b) differs from cleanup (llama3.2:1b), so the
    llm_verifier signal is produced instead of `skip_same_model`."""
    from manuallabor.contracts import ProjectConfig, Task
    from manuallabor.contracts.enums import SignalName
    from manuallabor.providers import ListSink, ProviderSet
    from manuallabor.scoring.pipeline import score_block
    from manuallabor.scoring.verifier import plan_verifier

    cfg = ProjectConfig(name="live")
    assert cfg.models.verifier is not None
    vprov = make_factory("ollama")(
        cfg.models.verifier, ListSink(), LLMCache(tmp_path / "vcache"), utc_now
    )
    plan = plan_verifier(cfg, lambda: ProviderSet(by_task={Task.verifier: vprov}))
    assert plan.ref is not None and plan.reason is None, plan  # not skip_same_model
    counters: Counter[str] = Counter()
    present = 0
    for e in entries:
        b = by_id[e.block_id].model_copy(update={"clean_text": e.clean_text})
        sc = score_block(b, ctxs[b.id], threshold=0.85, plan=plan, counters=counters)
        present += any(x.name == SignalName.llm_verifier for x in sc.signals)
    print(f"LIVE verifier {cfg.models.verifier.model}: signals={present} counters={dict(counters)}")
    assert counters["skip_same_model"] == 0
    assert present >= 1
