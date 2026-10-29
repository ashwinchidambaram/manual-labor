"""Backends for the provider contract suite: mock, HTTP replay (respx) and live."""

from __future__ import annotations

import base64
import copy
import json
import os
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from manuallabor.contracts import ModelRef, Task
from manuallabor.providers import ListSink, LLMCache, MockProvider
from manuallabor.providers.base import Provider, utc_now
from manuallabor.providers.registry import make_factory

REC = Path(__file__).parent / "recordings"
SECRET = "sk-test-SECRET"
IGNORED_PATHS = ("/api/tags", "/api/show")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
LIVE_MODELS = {"chat": "llama3.2:1b", "vision": "moondream", "embed": "nomic-embed-text"}
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}


def rec(name: str) -> dict[str, Any]:
    return json.loads((REC / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass
class Captured:
    method: str
    host: str
    path: str
    body: Any
    headers: dict[str, str]


def _set_text(fmt: str, body: dict[str, Any], text: str) -> dict[str, Any]:
    body = copy.deepcopy(body)
    if fmt == "ollama":
        body["message"]["content"] = text
    elif fmt == "anthropic":
        body["content"][0]["text"] = text
    else:
        body["choices"][0]["message"]["content"] = text
    return body


@dataclass
class Replay:
    """A scripted fake server for one vendor wire format."""

    fmt: str  # ollama | anthropic | openai
    queue: list[str] = field(default_factory=list)
    requests: list[Captured] = field(default_factory=list)
    digest: str | None = None
    drop_usage: bool = False
    prompt_tokens: int | None = None
    router: respx.MockRouter | None = None

    def script(self, *outcomes: str) -> None:
        self.queue.extend(outcomes)

    @property
    def inference(self) -> list[Captured]:
        return [r for r in self.requests if r.path not in IGNORED_PATHS]

    def temperatures(self) -> list[float]:
        out: list[float] = []
        for r in self.inference:
            if r.path.endswith(("embed", "embeddings")):
                continue
            b = r.body
            out.append(b["options"]["temperature"] if self.fmt == "ollama" else b["temperature"])
        return out

    # -- wire ------------------------------------------------------------
    def _wants_schema(self, body: dict[str, Any]) -> bool:
        if self.fmt == "ollama":
            return "format" in body
        if self.fmt == "anthropic":
            return "JSON Schema" in json.dumps(body.get("system", ""))
        return "response_format" in body

    def _ok(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        name = {
            "ollama": "ollama_chat_{}",
            "anthropic": "anthropic_messages_{}",
            "openai": "openai_chat_{}",
        }[self.fmt].format("json" if self._wants_schema(body) else "text")
        r = rec(name)
        return r["status"], r["json"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        headers = {
            k: ("<redacted>" if k in ("authorization", "x-api-key") else v)
            for k, v in request.headers.items()
        }
        cap = Captured(request.method, request.url.host, request.url.path, body, headers)
        self.requests.append(cap)
        path = request.url.path
        if self.fmt == "ollama" and path == "/api/tags":
            r = rec("ollama_tags")
            if self.digest is not None:
                r = copy.deepcopy(r)
                for m in r["json"]["models"]:
                    m["digest"] = self.digest
            return httpx.Response(r["status"], json=r["json"])
        if self.fmt == "ollama" and path == "/api/show":
            return httpx.Response(200, json=rec("ollama_show")["json"])
        outcome = self.queue.pop(0) if self.queue else "ok"
        if outcome == "timeout":
            raise httpx.ReadTimeout("scripted timeout", request=request)
        if outcome == "http_500":
            r = rec("error_500")
            return httpx.Response(r["status"], json=r["json"])
        if outcome == "http_401":
            r = rec("error_401_anthropic" if self.fmt == "anthropic" else "error_401_openai")
            return httpx.Response(r["status"], json=r["json"])
        if path.endswith(("embed", "embeddings")):
            r = rec("ollama_embed" if self.fmt == "ollama" else "openai_embeddings")
            return httpx.Response(r["status"], json=r["json"])
        status, js = self._ok(body or {})
        text = {
            "ok": None,
            "invalid_json": "this is not json",
            "schema_mismatch": '{"n": "seven"}',
            "empty": "",
        }[outcome]
        if text is not None:
            js = _set_text(self.fmt, js, text)
        js = copy.deepcopy(js)
        if self.drop_usage:
            for k in ("usage", "prompt_eval_count", "eval_count"):
                js.pop(k, None)
        if self.prompt_tokens is not None and self.fmt == "ollama":
            js["prompt_eval_count"] = self.prompt_tokens
        return httpx.Response(status, json=js)


@dataclass
class Backend:
    id: str
    kind: str  # mock | replay | live
    provider: str
    supports_embed: bool
    sink: ListSink
    cache_dir: Path
    build: Callable[[str, ListSink, LLMCache | None], Provider]
    replay: Replay | None = None
    spy_temps: list[float] = field(default_factory=list)
    spy_embeds: list[int] = field(default_factory=list)

    @property
    def can_script(self) -> bool:
        return self.replay is not None

    def make(self, role: str = "chat", *, cache: bool = True) -> Provider:
        c = LLMCache(self.cache_dir) if cache else None
        return self.build(role, self.sink, c)

    def inference_count(self) -> int:
        if self.replay is not None:
            return len(self.replay.inference)
        return len(self.spy_temps) + len(self.spy_embeds)

    def temperatures(self) -> list[float]:
        return self.replay.temperatures() if self.replay is not None else list(self.spy_temps)


def _ollama_missing() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as r:  # noqa: S310
            have = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception:
        return ["(Ollama is not reachable: start it with `ollama serve`)"]
    out = []
    for m in LIVE_MODELS.values():
        if m not in have and f"{m}:latest" not in have:
            out.append(f"ollama pull {m}")
    return out


def _spied(be: Backend) -> None:
    """Live backends: count raw model calls and record their temperature."""
    inner = be.build

    def build(role: str, sink: ListSink, cache: LLMCache | None) -> Provider:
        p = inner(role, sink, cache)
        complete, embed = p._complete, p._embed_raw  # type: ignore[attr-defined]

        def spy_complete(task, messages, schema, temperature):  # type: ignore[no-untyped-def]
            be.spy_temps.append(temperature)
            return complete(task, messages, schema, temperature)

        def spy_embed(task, texts):  # type: ignore[no-untyped-def]
            be.spy_embeds.append(len(texts))
            return embed(task, texts)

        p._complete = spy_complete  # type: ignore[attr-defined]
        p._embed_raw = spy_embed  # type: ignore[attr-defined]
        return p

    be.build = build


def _fast(p: Provider) -> Provider:
    p._sleep = lambda s: None  # type: ignore[attr-defined]
    return p


def _factory_build(
    name: str, models: dict[str, str], api_base: str | None, backend_ref: dict[str, Any]
) -> Callable[[str, ListSink, LLMCache | None], Provider]:
    def build(role: str, sink: ListSink, cache: LLMCache | None) -> Provider:
        model = backend_ref.get("override") or models[role]
        ref = ModelRef(provider=name, model=model, api_base=api_base)
        return _fast(make_factory(name)(ref, sink, cache, utc_now))

    return build


REPLAY_IDS = ["ollama-replay", "anthropic-replay", "openai-replay", "vllm-replay"]
LIVE_IDS = ["ollama-live", "anthropic-live", "openai-live"]
ALL_IDS = [
    "mock",
    *REPLAY_IDS,
    *[pytest.param(i, marks=pytest.mark.live) for i in LIVE_IDS],
]


@pytest.fixture(params=ALL_IDS)
def backend(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Backend]:
    bid: str = request.param
    sink = ListSink()
    cache_dir = tmp_path / "cache"
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    if bid == "mock":
        be = Backend(bid, "mock", "mock", True, sink, cache_dir, build=lambda r, s, c: None)  # type: ignore[arg-type,return-value]

        def build_mock(role: str, sink: ListSink, cache: LLMCache | None) -> Provider:
            p = MockProvider(
                sink=sink,
                cache=cache,
                responses={Task.cleanup: '{"n": 7}', Task.vision: '{"n": 7}'},
            )
            orig = p._chat_raw

            def spy(task, messages, schema, temperature):  # type: ignore[no-untyped-def]
                be.spy_temps.append(temperature)
                return orig(task, messages, schema, temperature)

            p._chat_raw = spy  # type: ignore[method-assign]
            return p

        be.build = build_mock
        yield be
        return
    if bid.endswith("-replay"):
        name = bid.removesuffix("-replay")
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
        monkeypatch.setenv("OPENAI_API_KEY", SECRET)
        fmt = {"ollama": "ollama", "anthropic": "anthropic", "openai": "openai", "vllm": "openai"}[
            name
        ]
        r = Replay(fmt)
        host_kw: dict[str, Any]
        api_base: str | None = None
        models = {"chat": "m-chat", "vision": "m-vision", "embed": "m-embed"}
        if name == "ollama":
            host_kw = {"host": "localhost"}
            models = {"chat": "llama3.2:1b", "vision": "moondream", "embed": "nomic-embed-text"}
        elif name == "anthropic":
            host_kw = {"host": "api.anthropic.com"}
            models = {"chat": "claude-haiku-4-5", "vision": "claude-sonnet-4-5", "embed": "none"}
        elif name == "openai":
            host_kw = {"host": "api.openai.com"}
        else:
            host_kw = {"host": "127.0.0.1"}
            api_base = "http://127.0.0.1:8000/v1"
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
            router.route(**host_kw).mock(side_effect=r.handler)
            r.router = router
            be = Backend(
                bid,
                "replay",
                name,
                name != "anthropic",
                sink,
                cache_dir,
                build=_factory_build(name, models, api_base, {}),
                replay=r,
            )
            yield be
        return
    # live
    if bid == "ollama-live":
        if os.environ.get("MANUALLABOR_LIVE") != "1":
            pytest.skip("set MANUALLABOR_LIVE=1 to run live backends")
        missing = _ollama_missing()
        if missing:
            pytest.skip("missing for the live gate, run yourself:\n  " + "\n  ".join(missing))
        be = Backend(
            bid,
            "live",
            "ollama",
            True,
            sink,
            cache_dir,
            build=_factory_build("ollama", LIVE_MODELS, None, {}),
        )
        _spied(be)
        yield be
        return
    # hosted live APIs are opt-in and need keys
    name = bid.removesuffix("-live")
    keyvar = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[name]
    if os.environ.get("MANUALLABOR_LIVE_API") != "1" or not os.environ.get(keyvar):
        pytest.skip(f"set MANUALLABOR_LIVE_API=1 and {keyvar} to run {bid}")
    live_models = {
        "anthropic": {k: "claude-haiku-4-5" for k in LIVE_MODELS},
        "openai": {
            "chat": "gpt-4o-mini",
            "vision": "gpt-4o-mini",
            "embed": "text-embedding-3-small",
        },
    }[name]
    be = Backend(
        bid,
        "live",
        name,
        name != "anthropic",
        sink,
        cache_dir,
        build=_factory_build(name, live_models, None, {}),
    )
    _spied(be)
    yield be
