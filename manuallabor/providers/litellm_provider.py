"""The one real provider implementation: LiteLLM behind `BaseProvider`.

LiteLLM is imported lazily (`_litellm()`); importing this module does not import it."""

from __future__ import annotations

import base64
import functools
import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, TypeVar

from manuallabor.contracts.config import ModelRef
from manuallabor.contracts.enums import Task
from manuallabor.contracts.llm import Message
from manuallabor.providers.base import (
    BaseProvider,
    Clock,
    LogSink,
    ProviderError,
    ProviderOutputError,
    RawChat,
    RawEmbed,
    utc_now,
)
from manuallabor.providers.cache import LLMCache
from manuallabor.providers.registry import BackendSpec, Endpoint

log = logging.getLogger(__name__)

T = TypeVar("T")

MAX_TOKENS: Final[dict[str, int]] = {
    "cleanup": 4096,
    "grouping": 2048,
    "verifier": 256,
    "vision": 1024,
    "metadata": 1024,
    "agent": 2048,
    "embeddings": 0,
}
OLLAMA_NUM_CTX: Final = 8192
OLLAMA_KEEP_ALIVE: Final = "10m"
EMBED_BATCH: Final = 64
RETRY_SLEEPS: Final = (1.0, 4.0)
_RETRIABLE_NAMES = frozenset(
    {
        "Timeout",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "RateLimitError",
        "BadGatewayError",
    }
)
_SECRET_PATTERNS = (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), re.compile(r"Bearer\s+\S+"))


@functools.cache
def _litellm() -> Any:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    litellm.telemetry = False
    litellm.drop_params = False
    litellm.suppress_debug_info = True
    litellm.success_callback = []
    litellm.failure_callback = []
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return litellm


def litellm_version() -> str | None:
    from importlib import metadata

    try:
        return metadata.version("litellm")
    except metadata.PackageNotFoundError:
        return None


def _redact(text: str, secrets: Sequence[str | None] = ()) -> str:
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "***")
    for pat in _SECRET_PATTERNS:
        text = pat.sub("***", text)
    return text


def _unfence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json|JSON)?[ \t]*\n(.*?)\n?```$", t, re.DOTALL)
    return m.group(1).strip() if m else text


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("unsupported image format (expected PNG, JPEG, GIF or WEBP)")


def _estimate(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 4)


def schema_instruction(schema: Mapping[str, Any]) -> str:
    return (
        "Reply with ONLY a JSON value valid against this JSON Schema, no prose, no code fence:\n"
        + json.dumps(dict(schema), sort_keys=True, separators=(",", ":"))
    )


_SEMAPHORES: dict[tuple[str, str, int], threading.BoundedSemaphore] = {}
_SEM_LOCK = threading.Lock()


def _concurrency(spec: BackendSpec) -> int:
    raw = os.environ.get("MANUALLABOR_MAX_CONCURRENCY", "").strip()
    if raw.isdigit() and int(raw) >= 1:
        return int(raw)
    return spec.max_concurrency


def _semaphore(spec: BackendSpec, base: str | None) -> threading.BoundedSemaphore:
    limit = _concurrency(spec)
    key = (spec.name, base or "", limit)
    with _SEM_LOCK:
        sem = _SEMAPHORES.get(key)
        if sem is None:
            sem = _SEMAPHORES[key] = threading.BoundedSemaphore(limit)
        return sem


class _FlagCache:
    """Cache proxy that records `usage.estimated` (the LLMCallLog schema has no such field)."""

    def __init__(self, inner: LLMCache, tl: threading.local) -> None:
        self._inner = inner
        self._tl = tl

    def get(self, key: str) -> dict[str, Any] | None:
        return self._inner.get(key)

    def put(self, key: str, entry: Mapping[str, Any]) -> None:
        if getattr(self._tl, "estimated", False):
            entry = {**entry, "usage": {**dict(entry.get("usage") or {}), "estimated": True}}
        self._inner.put(key, entry)


class LiteLLMProvider(BaseProvider):
    def __init__(
        self,
        ref: ModelRef,
        *,
        sink: LogSink,
        cache: LLMCache | None,
        clock: Clock = utc_now,
        spec: BackendSpec,
        endpoint: Endpoint,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tl = threading.local()
        super().__init__(
            ref,
            sink=sink,
            cache=_FlagCache(cache, self._tl) if cache is not None else None,  # type: ignore[arg-type]
            clock=clock,
        )
        self.spec = spec
        self.endpoint = endpoint
        self._sleep = sleep
        self._namespace: str | None = None

    def __repr__(self) -> str:
        return f"LiteLLMProvider({self.ref.provider}:{self.ref.model})"

    # -- identity --------------------------------------------------------
    @property
    def cache_namespace(self) -> str:
        if self._namespace is None:
            self._namespace = self._compute_namespace()
        return self._namespace

    def _compute_namespace(self) -> str:
        base = f"{self.ref.provider}:{self.ref.model}"
        if self.spec.name == "ollama":
            digest = self._ollama_digest()
            return f"{base}@{digest}" if digest else base
        if self.endpoint.api_base and self.spec.name not in ("anthropic", "ollama"):
            from urllib.parse import urlparse

            netloc = urlparse(self.endpoint.api_base).netloc or self.endpoint.api_base
            return f"{base}@{netloc}"
        return base

    def _ollama_digest(self) -> str | None:
        try:
            import httpx

            r = httpx.get(f"{self.endpoint.api_base}/api/tags", timeout=2.0)
            r.raise_for_status()
            models = r.json().get("models", [])
            wanted = {self.ref.model, f"{self.ref.model}:latest"}
            for m in models:
                if m.get("name") in wanted or m.get("model") in wanted:
                    digest = str(m.get("digest", ""))
                    if digest:
                        return digest[:12]
            raise LookupError(f"model {self.ref.model!r} not listed")
        except Exception as exc:
            log.warning(
                "cannot read the model digest from Ollama (%s); cache key uses the model name only",
                _redact(str(exc), [self.endpoint.api_key]),
            )
            return None

    # -- request plumbing ------------------------------------------------
    def _model_id(self, embed: bool = False) -> str:
        tmpl = self.spec.embed_id if embed else self.spec.chat_id
        assert tmpl is not None
        return tmpl.format(m=self.ref.model)

    def _common(self, task: Task, temperature: float) -> dict[str, Any]:
        if temperature != 0:
            raise ProviderError("temperature must be 0")
        kw: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": MAX_TOKENS.get(str(task), 1024) or 1024,
            "num_retries": 0,
            "timeout": self.spec.read_timeout,
        }
        if self.endpoint.api_base:
            kw["api_base"] = self.endpoint.api_base
        if self.endpoint.api_key and self.spec.name != "ollama":
            kw["api_key"] = self.endpoint.api_key
        if self.spec.name == "ollama":
            kw.update(seed=0, num_ctx=OLLAMA_NUM_CTX, keep_alive=OLLAMA_KEEP_ALIVE)
        elif self.spec.name != "anthropic":
            kw["seed"] = 0
        return kw

    def _pin_ollama_env(self) -> None:
        """LiteLLM's runtime model-info lookup (/api/show) ignores the per-call api_base and
        reads OLLAMA_API_BASE; pin it so that no request leaves OLLAMA_HOST."""
        if self.spec.name == "ollama" and self.endpoint.api_base:
            os.environ["OLLAMA_API_BASE"] = self.endpoint.api_base

    def _secrets(self) -> list[str | None]:
        return [self.endpoint.api_key]

    def _translate(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        msg = _redact(f"{name}: {exc}", self._secrets())
        if len(msg) > 600:
            msg = msg[:600] + "..."
        retriable = name in _RETRIABLE_NAMES or (
            isinstance(status, int) and (status >= 500 or status == 429)
        )
        if self.spec.name == "ollama" and (
            status == 404 or name == "NotFoundError" or "not found" in str(exc).lower()
        ):
            msg += f" (run: ollama pull {self.ref.model})"
            retriable = False
        return ProviderError(
            msg, provider=self.ref.provider, model=self.ref.model, retriable=retriable
        )

    def _call(self, fn: Callable[[], T]) -> T:
        sem = _semaphore(self.spec, self.endpoint.api_base)
        last: ProviderError | None = None
        for attempt in range(len(RETRY_SLEEPS) + 1):
            try:
                with sem:
                    return fn()
            except ProviderError as exc:
                last = exc
                if not exc.retriable:
                    raise
            except Exception as exc:
                last = self._translate(exc)
                if not last.retriable:
                    raise last from None
            if attempt < len(RETRY_SLEEPS):
                self._sleep(RETRY_SLEEPS[attempt])
        assert last is not None
        raise last

    # -- chat ------------------------------------------------------------
    def _build_messages(
        self, messages: Sequence[Message], schema: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in messages]
        if schema is not None and (self.spec.schema_mode == "prompt" or self.spec.name == "ollama"):
            instr = schema_instruction(schema)
            if out and out[0]["role"] == "system":
                out[0] = {"role": "system", "content": f"{out[0]['content']}\n\n{instr}"}
            else:
                out.insert(0, {"role": "system", "content": instr})
        return out

    def _complete(
        self,
        task: Task,
        messages: list[dict[str, Any]],
        schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> tuple[str, int | None, int | None]:
        kw = self._common(task, temperature)
        if schema is not None and self.spec.schema_mode == "native":
            kw["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": dict(schema), "strict": False},
            }
        lt = _litellm()
        self._pin_ollama_env()

        def go() -> Any:
            return lt.completion(model=self._model_id(), messages=messages, **kw)

        resp = self._call(go)
        try:
            text = resp.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError("malformed completion response", retriable=False) from exc
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", None) if usage else None
        ct = getattr(usage, "completion_tokens", None) if usage else None
        if self.spec.name == "ollama" and isinstance(pt, int) and pt >= OLLAMA_NUM_CTX:
            raise ProviderError(
                f"prompt truncated at num_ctx={OLLAMA_NUM_CTX} ({pt} prompt tokens)",
                retriable=False,
            )
        text = _unfence(text)
        if not text.strip():
            raise ProviderError("model returned an empty reply", retriable=False)
        return text, pt, ct

    def _run(
        self,
        task: Task,
        messages: list[dict[str, Any]],
        schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self._tl.estimated = False
        text, pt, ct = self._complete(task, messages, schema, temperature)
        if schema is not None:
            try:
                self._validate(task, text, schema)
            except ProviderOutputError as bad:
                follow = [
                    *messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": f"That reply was invalid: {bad}. "
                        "Reply with only valid JSON matching the schema.",
                    },
                ]
                text2, pt2, ct2 = self._complete(task, follow, schema, temperature)
                text = text2
                pt = pt + pt2 if pt is not None and pt2 is not None else pt2 or pt
                ct = ct + ct2 if ct is not None and ct2 is not None else ct2 or ct
        if not pt or not ct:
            self._tl.estimated = True
            pt = pt if pt else _estimate(json.dumps(messages, ensure_ascii=False))
            ct = ct if ct else _estimate(text)
        return RawChat(text, pt, ct)

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        return self._run(
            task, self._build_messages(messages, json_schema), json_schema, temperature
        )

    def _vision_raw(
        self,
        task: Task,
        image_bytes: bytes,
        prompt: str,
        temperature: float,
        json_schema: Mapping[str, Any] | None = None,
    ) -> RawChat:
        mime = _sniff_mime(image_bytes)
        url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        msgs = self._build_messages([], json_schema)
        msgs.append({"role": "user", "content": content})
        return self._run(task, msgs, json_schema, temperature)

    # -- embeddings ------------------------------------------------------
    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        if self.spec.embed_id is None:
            raise ProviderError(
                f"provider {self.spec.name!r} has no embeddings API; configure models.embeddings "
                "with ollama/openai/...",
                retriable=False,
            )
        if self.spec.name == "ollama" and any(not t.strip() for t in texts):
            raise ProviderError("cannot embed an empty string", retriable=False)
        lt = _litellm()
        self._pin_ollama_env()
        kw: dict[str, Any] = {"num_retries": 0, "timeout": self.spec.read_timeout}
        if self.endpoint.api_base:
            kw["api_base"] = self.endpoint.api_base
        if self.endpoint.api_key and self.spec.name != "ollama":
            kw["api_key"] = self.endpoint.api_key
        vectors: list[list[float]] = []
        tokens = 0
        for i in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[i : i + EMBED_BATCH])

            def go(batch: list[str] = batch) -> Any:
                return lt.embedding(model=self._model_id(embed=True), input=batch, **kw)

            resp = self._call(go)
            items = list(_get(resp, "data") or [])
            items.sort(key=lambda d: _get(d, "index") or 0)
            vectors.extend([list(_get(d, "embedding") or []) for d in items])
            usage = _get(resp, "usage")
            tokens += int(_get(usage, "prompt_tokens") or 0) if usage else 0
        return RawEmbed(vectors, tokens or None)


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)
