"""The one real provider implementation: LiteLLM behind `BaseProvider`.

LiteLLM is imported lazily (`_litellm()`); importing this module does not import it."""

from __future__ import annotations

import base64
import contextlib
import functools
import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
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
    "cleanup": 4096,  # ceiling; the per-call budget is `max_tokens_for`
    "grouping": 2048,
    "verifier": 256,
    "vision": 1024,
    "metadata": 1024,
    "agent": 2048,
    "embeddings": 0,
}
CLEANUP_MAX_TOKENS: Final = 4096
CLEANUP_HEADROOM: Final = 256
CHARS_PER_TOKEN: Final = 3.5  # conservative: real text is 3.5-4.5 chars per token
OLLAMA_MIN_EVAL_RATIO: Final = 0.8
# Upper bound on the tokens a chat template adds around the messages (role tags, BOS/EOS, a
# default system line); used only to decide that a prompt cannot have reached num_ctx.
OLLAMA_TEMPLATE_ALLOWANCE: Final = 256
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
    # Always offline: a user-set value never re-enables the remote cost-map fetch or telemetry.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_TELEMETRY"] = "False"
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


def _message_text(messages: Sequence[Mapping[str, Any]]) -> int:
    """Characters of text in wire-format messages (image payloads are not counted)."""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(str(x.get("text", ""))) for x in c if isinstance(x, Mapping))
    return n


def estimate_prompt_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    return math.ceil(_message_text(messages) / CHARS_PER_TOKEN)


def prompt_cannot_exceed_ctx(messages: Sequence[Mapping[str, Any]]) -> bool:
    """True when the prompt cannot have reached ``OLLAMA_NUM_CTX`` under any tokenizer Ollama
    runs: byte-level BPE and SentencePiece with byte fallback never emit more tokens than the
    text has UTF-8 bytes, and the chat template adds at most ``OLLAMA_TEMPLATE_ALLOWANCE``.
    Ollama only truncates a prompt that does not fit num_ctx, so such a prompt was not
    truncated whatever ``prompt_eval_count`` says (design 06, truncation guard). A message with
    a non-text part (an image) is never bounded this way: its tokens are not in the text."""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c.encode("utf-8"))
        elif isinstance(c, list):
            for x in c:
                if not isinstance(x, Mapping) or x.get("type", "text") != "text":
                    return False
                n += len(str(x.get("text", "")).encode("utf-8"))
        elif c is not None:
            return False
    return n + OLLAMA_TEMPLATE_ALLOWANCE < OLLAMA_NUM_CTX


def max_tokens_for(task: Task | str, messages: Sequence[Mapping[str, Any]]) -> int:
    """Reply budget. Cleanup output is about as long as its input, so it scales with the
    prompt (2x + headroom, capped); every other task has a fixed budget."""
    if str(task) == "cleanup":
        return min(CLEANUP_MAX_TOKENS, 2 * estimate_prompt_tokens(messages) + CLEANUP_HEADROOM)
    return MAX_TOKENS.get(str(task), 1024) or 1024


def schema_instruction(schema: Mapping[str, Any]) -> str:
    return (
        "Reply with ONLY a JSON value valid against this JSON Schema, no prose, no code fence:\n"
        + json.dumps(dict(schema), sort_keys=True, separators=(",", ":"))
    )


_SEMAPHORES: dict[tuple[str, str, int], threading.BoundedSemaphore] = {}
_SEM_LOCK = threading.Lock()
_OLLAMA_ENV = threading.Condition()


class _Pin:
    count = 0
    base: str | None = None
    prior: str | None = None


_OLLAMA_PIN = _Pin()


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

    def _common(
        self, task: Task, temperature: float, messages: Sequence[Mapping[str, Any]] = ()
    ) -> dict[str, Any]:
        if temperature != 0:
            raise ProviderError("temperature must be 0")
        kw: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens_for(task, messages),
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

    @contextlib.contextmanager
    def _ollama_env(self) -> Iterator[None]:
        """LiteLLM's runtime model-info lookup (/api/show) ignores the per-call api_base
        (0.x: `get_runtime_model_info` is called without it) and reads OLLAMA_API_BASE. Set it
        only while calls are in flight (refcounted under a lock) and restore the previous value,
        so no request leaves OLLAMA_HOST and the process environment is left as found."""
        if self.spec.name != "ollama" or not self.endpoint.api_base:
            yield
            return
        base = self.endpoint.api_base
        with _OLLAMA_ENV:
            # calls with the same base share the pin (so they stay concurrent); a different
            # base waits until the in-flight ones finish
            while _OLLAMA_PIN.count and _OLLAMA_PIN.base != base:
                _OLLAMA_ENV.wait()
            if _OLLAMA_PIN.count == 0:
                _OLLAMA_PIN.prior = os.environ.get("OLLAMA_API_BASE")
                _OLLAMA_PIN.base = base
                os.environ["OLLAMA_API_BASE"] = base
            _OLLAMA_PIN.count += 1
        try:
            yield
        finally:
            with _OLLAMA_ENV:
                _OLLAMA_PIN.count -= 1
                if _OLLAMA_PIN.count == 0:
                    if _OLLAMA_PIN.prior is None:
                        os.environ.pop("OLLAMA_API_BASE", None)
                    else:
                        os.environ["OLLAMA_API_BASE"] = _OLLAMA_PIN.prior
                    _OLLAMA_ENV.notify_all()

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
        kw = self._common(task, temperature, messages)
        estimate = estimate_prompt_tokens(messages)
        if self.spec.name == "ollama" and estimate > OLLAMA_NUM_CTX:
            raise ProviderError(
                f"prompt truncated: about {estimate} prompt tokens exceed "
                f"num_ctx={OLLAMA_NUM_CTX}; no request was sent",
                retriable=False,
            )
        if schema is not None and self.spec.schema_mode == "native":
            kw["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": dict(schema), "strict": False},
            }
        lt = _litellm()

        def go() -> Any:
            with self._ollama_env():
                return lt.completion(model=self._model_id(), messages=messages, **kw)

        resp = self._call(go)
        try:
            text = resp.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError("malformed completion response", retriable=False) from exc
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", None) if usage else None
        ct = getattr(usage, "completion_tokens", None) if usage else None
        # The ratio check only applies to a prompt that could have exceeded num_ctx: for a short
        # prompt the estimate (chars / 3.5, deliberately high for budgets) routinely runs 20-28%
        # above the real count, and 71 of 124 verifier calls were dropped as "truncated".
        if (
            self.spec.name == "ollama"
            and isinstance(pt, int)
            and (
                pt >= OLLAMA_NUM_CTX
                or (
                    pt < OLLAMA_MIN_EVAL_RATIO * estimate and not prompt_cannot_exceed_ctx(messages)
                )
            )
        ):
            raise ProviderError(
                f"prompt truncated: Ollama evaluated {pt} prompt tokens of about {estimate} "
                f"(num_ctx={OLLAMA_NUM_CTX})",
                retriable=False,
            )
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            raise ProviderError(
                f"response truncated at max_tokens={kw['max_tokens']}",
                retriable=False,
                truncated=True,
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
        self._tl.estimated = False
        lt = _litellm()
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
                with self._ollama_env():
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
