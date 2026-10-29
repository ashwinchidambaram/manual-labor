"""Design 10 test 31 (live): the seeded pass with a real small agent model and a real vision
reader. Runs only with MANUALLABOR_LIVE=1 and the models pulled; otherwise `SKIP live:`.

The invariant under test is the hard one: nothing is accepted that failed a check, whatever
the model said."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import pytest

from manuallabor.contracts import ModelRef
from manuallabor.contracts.enums import ProposalStatus, Task
from manuallabor.providers import ProviderSet
from manuallabor.providers.base import utc_now
from manuallabor.providers.cache import LLMCache
from manuallabor.providers.registry import make_factory
from tests.agent.conftest import AEnv

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if "://" not in OLLAMA:
    OLLAMA = "http://" + OLLAMA
AGENT_MODEL, VISION_MODEL = "llama3.2:1b", "moondream"


def _missing() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA.rstrip('/')}/api/tags", timeout=3) as r:  # noqa: S310
            names = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception:
        return ["Ollama is not reachable"]
    have = names | {n.removesuffix(":latest") for n in names}
    return [f"ollama pull {m}" for m in (AGENT_MODEL, VISION_MODEL) if m not in have]


_LIVE = os.environ.get("MANUALLABOR_LIVE") == "1"
_MISSING = _missing() if _LIVE else []
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE or bool(_MISSING),
        reason="SKIP live: " + ("set MANUALLABOR_LIVE=1" if not _LIVE else "; ".join(_MISSING)),
    ),
]


def test_31_live_pass_accepts_nothing_that_failed(aenv: AEnv, capsys: Any) -> None:
    flags = aenv.seed()
    cache = LLMCache(aenv.paths.root / ".llm_cache")

    def real(model: str) -> Any:
        return make_factory("ollama")(
            ModelRef(provider="ollama", model=model), aenv.sink, cache, utc_now
        )

    mock = aenv.providers()
    ps = ProviderSet(
        by_task={**mock.by_task, Task.agent: real(AGENT_MODEL), Task.vision: real(VISION_MODEL)}
    )
    from manuallabor.agent.pipeline import run_agent_plan

    plan, _skips = aenv.agent.plan(None, None)
    events: list[dict[str, Any]] = []

    def emit(o: dict[str, Any]) -> None:
        events.append(o)
        if o.get("event") in ("proposal", "agent_outcome"):
            aenv.agent.ingest_event("job-live", o)

    run_agent_plan(aenv.paths, plan.model_dump(mode="json"), lambda: ps, emit, lambda: False)
    props = aenv.agent.proposals()
    outcomes = [e for e in events if e.get("event") == "agent_outcome"]
    assert len(props) + len(outcomes) == len(flags)
    for p in props:
        assert p.rechecks, p.id
    done = aenv.agent.accept_all_passing(None, "live-all")
    accepted_failing = [p for p in done if not p.all_checks_passed]
    passing = [p for p in props if p.all_checks_passed]
    with capsys.disabled():
        print(
            f"\nlive: attempted={len(flags)} proposals={len(props)} outcomes={len(outcomes)} "
            f"passing={len(passing)} accepted={len(done)} "
            f"accepted_with_failing_check={len(accepted_failing)}"
        )
        for o in outcomes:
            print("  outcome:", o["flag_id"], o["outcome"], (o.get("detail") or "")[:140])
    assert accepted_failing == []
    for p in aenv.agent.proposals():
        if not p.all_checks_passed:
            assert p.status == ProposalStatus.pending
