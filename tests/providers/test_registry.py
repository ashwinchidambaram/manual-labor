"""T2 registry, T12 cache namespace, T14 concurrency."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import pytest
import respx

from manuallabor.contracts import Message, ModelRef, Task
from manuallabor.providers import (
    DEFAULT_FACTORIES,
    ListSink,
    LLMCache,
    ProviderError,
    build_provider_set,
)
from manuallabor.providers.base import utc_now
from manuallabor.providers.litellm_provider import LiteLLMProvider
from manuallabor.providers.registry import make_factory, normalize_ollama_host, resolve_endpoint
from tests.providers.contract.conftest import Replay

CHAT = [Message(role="user", content="hi")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "http://localhost:11434"),
        ("", "http://localhost:11434"),
        ("myhost", "http://myhost:11434"),
        ("myhost:9999", "http://myhost:9999"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:11500", "http://127.0.0.1:11500"),
        ("https://x/", "https://x"),
        ("http://box:11434/", "http://box:11434"),
    ],
)
def test_normalize_ollama_host(value: str | None, expected: str) -> None:
    assert normalize_ollama_host(value) == expected


def build(provider: str, **kw: str | None) -> object:
    return make_factory(provider)(
        ModelRef(provider=provider, model="m", **kw),
        ListSink(),
        None,
        utc_now,  # type: ignore[arg-type]
    )


def test_unknown_provider_names_it(tmp_path: Path) -> None:
    from manuallabor.contracts import ProjectConfig, TaskModels

    ref = ModelRef(provider="nope", model="x")
    cfg = ProjectConfig(
        name="p",
        models=TaskModels(
            cleanup=ref,
            grouping=ref,
            vision=ref,
            embeddings=ref,
            verifier=ModelRef(provider="mock", model="mock-verifier"),
        ),
    )
    with pytest.raises(ProviderError, match="nope"):
        build_provider_set(cfg, cache_dir=None, sink=ListSink())


@pytest.mark.parametrize(
    ("provider", "var"), [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]
)
def test_missing_key_names_variable_only(
    provider: str, var: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ProviderError, match=var) as ei:
        build(provider)
    assert ei.value.retriable is False
    monkeypatch.setenv(var, "sk-test-SECRET")
    p = build(provider)
    assert "sk-test-SECRET" not in repr(p) and "sk-test-SECRET" not in repr(p.endpoint)  # type: ignore[attr-defined]


def test_custom_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MY_KEY", "abc-123456")
    assert build("anthropic", api_key_env="MY_KEY")  # type: ignore[arg-type]
    with pytest.raises(ProviderError, match="OTHER_KEY"):
        build("anthropic", api_key_env="OTHER_KEY")


@pytest.mark.parametrize("name", ["vllm", "llamacpp"])
def test_local_openai_needs_base(name: str) -> None:
    with pytest.raises(ProviderError, match="api_base"):
        build(name)
    assert build(name, api_base="http://127.0.0.1:8000/v1")


def test_openai_aliases_same_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k-123456")
    a = build("openai")
    b = build("openai_compatible")
    assert type(a) is type(b) is LiteLLMProvider


def test_openai_compatible_with_base_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert build("openai_compatible", api_base="http://127.0.0.1:1234/v1")


def test_factories_registered() -> None:
    assert {
        "mock",
        "ollama",
        "anthropic",
        "openai",
        "openai_compatible",
        "vllm",
        "llamacpp",
    } <= set(DEFAULT_FACTORIES)


def test_ollama_endpoint_from_env() -> None:
    ep = resolve_endpoint(ModelRef(provider="ollama", model="m"), {"OLLAMA_HOST": "box:1"})
    assert ep.api_base == "http://box:1"
    ep2 = resolve_endpoint(
        ModelRef(provider="ollama", model="m", api_base="http://other:2"), {"OLLAMA_HOST": "box:1"}
    )
    assert ep2.api_base == "http://other:2"


# -- T12 ---------------------------------------------------------------------
def _ollama(digest: str | None = None) -> tuple[Replay, respx.MockRouter]:
    r = Replay("ollama", digest=digest)
    router = respx.mock(assert_all_mocked=True, assert_all_called=False)
    router.route(host="localhost").mock(side_effect=r.handler)
    return r, router


def test_t12_digest_change_changes_namespace_and_hash(tmp_path: Path) -> None:
    hashes = []
    for digest in ("aaaaaaaaaaaa1111", "bbbbbbbbbbbb2222"):
        r, router = _ollama(digest)
        with router:
            p = make_factory("ollama")(
                ModelRef(provider="ollama", model="llama3.2:1b"), ListSink(), None, utc_now
            )
            assert p.cache_namespace == f"ollama:llama3.2:1b@{digest[:12]}"
            hashes.append(p.chat(Task.cleanup, CHAT).log.input_hash)
            assert sum(1 for q in r.requests if q.path == "/api/tags") == 1
    assert hashes[0] != hashes[1]


def test_t12_digest_failure_falls_back_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = respx.mock(assert_all_mocked=True, assert_all_called=False)
    router.route(host="localhost").mock(side_effect=httpx.ConnectError("down"))
    with router:
        p = make_factory("ollama")(
            ModelRef(provider="ollama", model="llama3.2:1b"), ListSink(), None, utc_now
        )
        with caplog.at_level("WARNING"):
            assert p.cache_namespace == "ollama:llama3.2:1b"
            assert p.cache_namespace == "ollama:llama3.2:1b"
    assert sum("model digest" in r.message for r in caplog.records) == 1


def test_t12_openai_compatible_bases_do_not_collide() -> None:
    a = build("vllm", api_base="http://127.0.0.1:8000/v1")
    b = build("vllm", api_base="http://127.0.0.1:8001/v1")
    assert a.cache_namespace != b.cache_namespace  # type: ignore[attr-defined]
    assert a.cache_namespace == "vllm:m@127.0.0.1:8000"  # type: ignore[attr-defined]


# -- T14 ---------------------------------------------------------------------
def _concurrency_peak(max_env: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> int:
    if max_env is not None:
        monkeypatch.setenv("MANUALLABOR_MAX_CONCURRENCY", max_env)
    else:
        monkeypatch.delenv("MANUALLABOR_MAX_CONCURRENCY", raising=False)
    r = Replay("ollama")
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()
    base = r.handler

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.15)
            try:
                return base(request)
            finally:
                with lock:
                    state["now"] -= 1
        return base(request)

    router = respx.mock(assert_all_mocked=True, assert_all_called=False)
    router.route(host="localhost").mock(side_effect=slow)
    with router:
        p = make_factory("ollama")(
            ModelRef(provider="ollama", model="llama3.2:1b"),
            ListSink(),
            LLMCache(tmp_path / "c"),
            utc_now,
        )
        _ = p.cache_namespace  # resolve the digest before threads start
        threads = [
            threading.Thread(
                target=lambda i=i: p.chat(Task.cleanup, [Message(role="user", content=f"q{i}")])
            )
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return state["peak"]


def test_t14_ollama_one_in_flight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _concurrency_peak(None, monkeypatch, tmp_path) == 1


def test_t14_env_override_allows_two(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _concurrency_peak("2", monkeypatch, tmp_path) == 2
