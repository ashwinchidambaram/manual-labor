"""The provider contract suite (T1 a-m, T13, T15): identical assertions for every backend."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path

import pytest

from manuallabor.contracts import Message
from manuallabor.contracts.enums import Task
from manuallabor.contracts.llm import LLMCallLog
from manuallabor.providers import JsonlSink, ProviderError, ProviderOutputError
from tests.providers.contract.conftest import PNG, SCHEMA, SECRET, Backend

CHAT = [Message(role="user", content="Reply with the single word: ok")]
JSON_CHAT = [Message(role="user", content="Return a JSON object with n set to the integer 7.")]
VISION_PROMPT = "Describe this image in one short sentence."


def needs_script(be: Backend) -> None:
    if not be.can_script:
        pytest.skip("failure injection needs a scripted backend")


def test_a_chat(backend: Backend) -> None:
    res = backend.make().chat(Task.cleanup, CHAT)
    assert isinstance(res.text, str) and res.text.strip()
    assert res.log.kind == "chat"


def test_b_json_chat(backend: Backend) -> None:
    res = backend.make().chat(Task.cleanup, JSON_CHAT, json_schema=SCHEMA)
    assert isinstance(res.parsed, dict) and isinstance(res.parsed["n"], int)
    if backend.kind != "live":
        assert res.parsed == {"n": 7}


def test_c_json_invalid_then_valid(backend: Backend) -> None:
    needs_script(backend)
    assert backend.replay is not None
    backend.replay.script("invalid_json", "ok")
    res = backend.make().chat(Task.cleanup, JSON_CHAT, json_schema=SCHEMA)
    assert res.parsed == {"n": 7}
    assert backend.inference_count() == 2
    assert len(backend.sink) == 1 and backend.sink[0].ok


@pytest.mark.parametrize("bad", ["invalid_json", "schema_mismatch"])
def test_d_json_invalid_twice(backend: Backend, bad: str) -> None:
    needs_script(backend)
    assert backend.replay is not None
    backend.replay.script(bad, bad)
    p = backend.make()
    with pytest.raises(ProviderOutputError):
        p.chat(Task.cleanup, JSON_CHAT, json_schema=SCHEMA)
    assert backend.inference_count() == 2
    assert len(backend.sink) == 1 and backend.sink[0].ok is False
    assert not list(backend.cache_dir.glob("*.json")) if backend.cache_dir.exists() else True
    res = p.chat(Task.cleanup, JSON_CHAT, json_schema=SCHEMA)  # recovered: a third call asks again
    assert res.parsed == {"n": 7} and backend.inference_count() == 3


def test_e_vision(backend: Backend) -> None:
    if backend.id == "mock":
        pytest.skip("mock vision has no wire format")
    res = backend.make("vision").vision(Task.vision, PNG, VISION_PROMPT)
    assert res.text.strip()
    assert res.log.kind == "vision"
    if backend.replay is None:
        return
    body = backend.replay.inference[0].body
    if backend.replay.fmt == "ollama":
        import base64

        assert base64.b64decode(body["messages"][-1]["images"][0]) == PNG
    elif backend.replay.fmt == "anthropic":
        import base64

        block = body["messages"][0]["content"][1]
        assert block["type"] == "image" and block["source"]["type"] == "base64"
        assert base64.b64decode(block["source"]["data"]) == PNG
    else:
        import base64

        url = body["messages"][0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_f_embed(backend: Backend) -> None:
    p = backend.make("embed")
    texts = ["Tighten the M8 bolts", "wiring diagram for the fuse box", "belt tension"]
    if not backend.supports_embed:
        with pytest.raises(ProviderError, match="no embeddings"):
            p.embed(Task.embeddings, texts)
        return
    vecs = p.embed(Task.embeddings, texts)
    assert len(vecs) == 3
    dim = len(vecs[0])
    assert dim > 0
    assert all(len(v) == dim and all(math.isfinite(x) for x in v) for v in vecs)


def test_g_temperature_zero(backend: Backend) -> None:
    p = backend.make()
    p.chat(Task.cleanup, CHAT)
    p.chat(Task.cleanup, JSON_CHAT, json_schema=SCHEMA)
    if backend.id != "mock":
        backend.make("vision").vision(Task.vision, PNG, VISION_PROMPT)
    temps = backend.temperatures()
    assert temps and all(t == 0 for t in temps), temps


def test_h_log_line(backend: Backend, tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "calls.jsonl")
    p = backend.build("chat", backend.sink, None)
    p._sink = lambda log: (backend.sink(log), sink(log))  # type: ignore[attr-defined]
    p.chat(Task.cleanup, CHAT)
    assert len(backend.sink) == 1
    log = backend.sink[0]
    assert log.task == Task.cleanup and log.kind == "chat" and log.ok
    assert len(log.input_hash) == 64 and log.latency_ms >= 0 and log.cached is False
    assert log.provider == backend.provider
    assert isinstance(log.prompt_tokens, int) and isinstance(log.completion_tokens, int)
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert LLMCallLog.model_validate_json(lines[0]) == log


def test_i_cache_hit(backend: Backend) -> None:
    p = backend.make()
    first = p.chat(Task.cleanup, CHAT)
    n = backend.inference_count()
    second = p.chat(Task.cleanup, CHAT)
    assert second.log.cached is True and first.log.cached is False
    assert backend.inference_count() == n
    assert second.text == first.text
    assert second.log.input_hash == first.log.input_hash
    assert len(backend.sink) == 2


@pytest.mark.parametrize(
    ("outcome", "retriable", "attempts"),
    [("http_500", True, 3), ("timeout", True, 3), ("empty", False, 1)],
)
def test_j_failures_not_cached(
    backend: Backend, outcome: str, retriable: bool, attempts: int
) -> None:
    needs_script(backend)
    assert backend.replay is not None
    backend.replay.script(*[outcome] * attempts)
    p = backend.make()
    with pytest.raises(ProviderError) as ei:
        p.chat(Task.cleanup, CHAT)
    assert ei.value.retriable is retriable
    assert backend.inference_count() == attempts
    assert backend.sink[-1].ok is False
    ok = p.chat(Task.cleanup, CHAT)  # recovered: nothing was cached, so it asks again
    assert ok.text and backend.inference_count() == attempts + 1


def test_k_non_retriable_auth(backend: Backend) -> None:
    needs_script(backend)
    assert backend.replay is not None
    backend.replay.script("http_401")
    with pytest.raises(ProviderError) as ei:
        backend.make().chat(Task.cleanup, CHAT)
    assert ei.value.retriable is False
    assert backend.inference_count() == 1
    assert SECRET not in str(ei.value)
    assert SECRET not in (backend.sink[-1].error or "")


def test_l_key_hygiene(backend: Backend, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    needs_script(backend)
    assert backend.replay is not None
    caplog.set_level(logging.DEBUG)
    sink = JsonlSink(tmp_path / "calls.jsonl")
    backend.replay.script("http_401")
    p = backend.build("chat", backend.sink, None)
    p._sink = lambda log: (backend.sink(log), sink(log))  # type: ignore[attr-defined]
    with pytest.raises(ProviderError) as ei:
        p.chat(Task.cleanup, CHAT)
    p.chat(Task.cleanup, CHAT)
    blob = (tmp_path / "calls.jsonl").read_text()
    blob += (
        "".join(f.read_text() for f in backend.cache_dir.glob("*") if f.is_file())
        if backend.cache_dir.exists()
        else ""
    )
    blob += str(ei.value) + repr(ei.value) + caplog.text + repr(p)
    assert SECRET not in blob
    assert all(SECRET not in str(r) for r in backend.sink)


def test_m_namespace(backend: Backend) -> None:
    a, b = backend.make(), backend.make()
    assert a.cache_namespace == b.cache_namespace
    if backend.kind != "replay":
        return
    other = backend.build("vision", backend.sink, None)  # a different model id
    assert other.cache_namespace != a.cache_namespace
    ra = a.chat(Task.cleanup, CHAT)
    rb = other.chat(Task.cleanup, CHAT)
    assert ra.log.input_hash != rb.log.input_hash


# -- T13 / T15 ---------------------------------------------------------------
def test_t13_usage_logged_and_estimated(backend: Backend) -> None:
    if backend.replay is None:
        pytest.skip("usage shapes are scripted")
    p = backend.make()
    r1 = p.chat(Task.cleanup, CHAT)
    assert r1.log.prompt_tokens is not None and r1.log.completion_tokens is not None
    if backend.replay.fmt != "ollama":
        assert (r1.log.prompt_tokens, r1.log.completion_tokens) == (10, 5)
    else:
        assert (r1.log.prompt_tokens, r1.log.completion_tokens) == (12, 4)
    entry = json.loads(next(backend.cache_dir.glob("*.json")).read_text())
    assert "estimated" not in entry["usage"]
    if backend.replay.fmt == "anthropic":
        return  # usage is mandatory in the Messages API; nothing to drop
    # no usage in the reply -> ceil(len/4) on both sides, flagged only in the cache entry
    backend.replay.drop_usage = True
    msgs = [Message(role="user", content="a different prompt 123456789")]
    r2 = p.chat(Task.cleanup, msgs)
    assert r2.log.prompt_tokens is not None and r2.log.prompt_tokens > 0
    if backend.replay.fmt == "ollama":
        return  # LiteLLM counts tokens itself when Ollama omits them; our fallback is not hit
    assert r2.log.completion_tokens == math.ceil(len(r2.text.encode()) / 4)
    entry2 = json.loads((backend.cache_dir / f"{r2.log.input_hash}.json").read_text())
    assert entry2["usage"]["estimated"] is True
    assert entry2["usage"]["prompt_tokens"] == r2.log.prompt_tokens


def test_t15_truncation(backend: Backend) -> None:
    if backend.replay is None or backend.replay.fmt != "ollama":
        pytest.skip("num_ctx truncation applies to Ollama")
    backend.replay.prompt_tokens = 8192
    p = backend.make()
    with pytest.raises(ProviderError, match="truncated") as ei:
        p.chat(Task.cleanup, CHAT)
    assert ei.value.retriable is False
    assert not list(backend.cache_dir.glob("*.json")) if backend.cache_dir.exists() else True
    assert hashlib  # keep import used for debugging helpers
