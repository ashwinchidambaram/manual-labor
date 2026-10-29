"""Live: Ollama must never silently truncate a long prompt (MANUALLABOR_LIVE=1, llama3.2:1b)."""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

from manuallabor.contracts import Message, ModelRef, Task
from manuallabor.providers import ListSink, ProviderError
from manuallabor.providers.base import utc_now
from manuallabor.providers.registry import make_factory

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if "://" not in OLLAMA:
    OLLAMA = "http://" + OLLAMA
MODEL = "llama3.2:1b"


def _ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA.rstrip('/')}/api/tags", timeout=3) as r:  # noqa: S310
            names = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception:
        return False
    return MODEL in names or f"{MODEL}:latest" in names


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MANUALLABOR_LIVE") != "1" or not _ready(),
        reason=f"set MANUALLABOR_LIVE=1 and run yourself: ollama pull {MODEL}",
    ),
]


def _provider() -> tuple[object, ListSink]:
    sink = ListSink()
    return make_factory("ollama")(
        ModelRef(provider="ollama", model=MODEL), sink, None, utc_now
    ), sink


def test_long_prompt_is_honoured_or_refused() -> None:
    """The reviewer's 1,200-step prompt (~8.4k real tokens, just over num_ctx=8192): it used to
    be accepted with prompt_eval_count=4098 (silently cut). Now: an error, never a short count."""
    p, sink = _provider()
    prompt = " ".join(f"step{i} tighten bolt {i}." for i in range(1200))
    try:
        res = p.chat(Task.verifier, [Message(role="user", content=prompt)])  # type: ignore[attr-defined]
    except ProviderError as exc:
        print("LIVE 1200-step prompt: ProviderError:", str(exc)[:120])
        assert "truncated" in str(exc) and exc.retriable is False
        return
    print("LIVE 1200-step prompt: prompt_eval_count =", res.log.prompt_tokens)
    assert res.log.prompt_tokens is not None and res.log.prompt_tokens > 4096


def test_900_step_prompt_reaches_the_model_whole() -> None:
    """Below num_ctx the option is honoured: all ~6.3k tokens are evaluated (not 4096)."""
    p, _ = _provider()
    prompt = (
        " ".join(f"step{i} tighten bolt {i}." for i in range(900))
        + "\n\nIgnore the list above. Reply with the single word: ok"
    )
    res = p.chat(Task.verifier, [Message(role="user", content=prompt)])  # type: ignore[attr-defined]
    print("LIVE 900-step prompt: prompt_eval_count =", res.log.prompt_tokens)
    assert res.log.prompt_tokens is not None and res.log.prompt_tokens > 6000


def test_20k_token_prompt_fails_before_any_request() -> None:
    p, sink = _provider()
    prompt = " ".join(f"step{i} tighten bolt {i}." for i in range(3000))  # ~20k tokens
    with pytest.raises(ProviderError, match="no request was sent"):
        p.chat(Task.verifier, [Message(role="user", content=prompt)])  # type: ignore[attr-defined]
    assert len(sink) == 1 and sink[0].ok is False
    assert sink[0].latency_ms < 1000  # nothing was sent to the model
