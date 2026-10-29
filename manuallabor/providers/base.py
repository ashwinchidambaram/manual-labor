"""Provider protocol, base class (cache, logging, validation) and provider set."""

from __future__ import annotations

import json
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from jsonschema import Draft202012Validator

from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import CallKind, Task
from manuallabor.contracts.llm import ChatResult, LLMCallLog, Message
from manuallabor.providers.cache import LLMCache, sha256_hex

TEMPERATURE: Final = 0.0
RAW_OPEN, RAW_CLOSE = "<raw>", "</raw>"

LogSink = Callable[[LLMCallLog], None]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        task: Task | None = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.task = task
        self.retriable = retriable


class ProviderOutputError(ProviderError):
    def __init__(self, message: str, *, raw_text: str, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.raw_text = raw_text


@dataclass(frozen=True)
class RawChat:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class RawEmbed:
    vectors: list[list[float]]
    prompt_tokens: int | None = None


class Provider(Protocol):
    ref: ModelRef

    @property
    def cache_namespace(self) -> str: ...

    def chat(
        self,
        task: Task,
        messages: Sequence[Message],
        *,
        json_schema: Mapping[str, Any] | None = None,
    ) -> ChatResult: ...

    def vision(
        self,
        task: Task,
        image_bytes: bytes,
        prompt: str,
        *,
        json_schema: Mapping[str, Any] | None = None,
    ) -> ChatResult: ...

    def embed(self, task: Task, texts: Sequence[str]) -> list[list[float]]: ...


class BaseProvider(ABC):
    def __init__(
        self,
        ref: ModelRef,
        *,
        sink: LogSink,
        cache: LLMCache | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.ref = ref
        self._sink = sink
        self._cache = cache
        self._clock = clock

    @abstractmethod
    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat: ...

    @abstractmethod
    def _vision_raw(
        self,
        task: Task,
        image_bytes: bytes,
        prompt: str,
        temperature: float,
        json_schema: Mapping[str, Any] | None = None,
    ) -> RawChat: ...

    @abstractmethod
    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed: ...

    @property
    def cache_namespace(self) -> str:
        """Identity mixed into every cache key. Subclasses whose output depends on more
        than (provider, model) must extend it."""
        return f"{self.ref.provider}:{self.ref.model}"

    # -- helpers ---------------------------------------------------------
    def _err(self, task: Task, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            if not exc.provider:
                exc.provider, exc.model = self.ref.provider, self.ref.model
            if exc.task is None:
                exc.task = task
            return exc
        return ProviderError(
            f"{type(exc).__name__}: {exc}",
            provider=self.ref.provider,
            model=self.ref.model,
            task=task,
            retriable=False,
        )

    def _emit(
        self,
        task: Task,
        kind: CallKind,
        key: str,
        t0: float,
        *,
        cached: bool,
        usage: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> LLMCallLog:
        usage = usage or {}
        entry = LLMCallLog(
            task=task,
            kind=kind,
            provider=self.ref.provider,
            model=self.ref.model,
            input_hash=key,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            cached=cached,
            ok=error is None,
            error=error,
            timestamp=self._clock(),
        )
        self._sink(entry)
        return entry

    def _validate(self, task: Task, text: str, schema: Mapping[str, Any] | None) -> Any | None:
        if schema is None:
            return None
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise ProviderOutputError(
                f"output is not valid JSON: {exc}",
                raw_text=text,
                provider=self.ref.provider,
                model=self.ref.model,
                task=task,
            ) from exc
        errors = sorted(
            Draft202012Validator(dict(schema)).iter_errors(parsed), key=lambda e: list(e.path)
        )
        if errors:
            raise ProviderOutputError(
                f"output does not match schema: {errors[0].message}",
                raw_text=text,
                provider=self.ref.provider,
                model=self.ref.model,
                task=task,
            )
        return parsed

    def _check_vectors(
        self, task: Task, vectors: Any, expected: int, *, round_values: bool
    ) -> list[list[float]]:
        def fail(msg: str) -> ProviderError:
            return ProviderError(
                f"embedding output invalid: {msg}",
                provider=self.ref.provider,
                model=self.ref.model,
                task=task,
            )

        if not isinstance(vectors, list) or len(vectors) != expected:
            got = len(vectors) if isinstance(vectors, list) else type(vectors).__name__
            raise fail(f"expected {expected} vectors, got {got}")
        out: list[list[float]] = []
        for v in vectors:
            if not isinstance(v, list) or not v:
                raise fail("each vector must be a non-empty list")
            if any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                for x in v
            ):
                raise fail("vector values must be finite numbers")
            out.append([round(float(x), 6) + 0.0 if round_values else float(x) for x in v])
        if len({len(v) for v in out}) > 1:
            raise fail("vectors must all have the same length")
        return out

    def _text_call(
        self,
        task: Task,
        kind: CallKind,
        inputs: dict[str, Any],
        schema: Mapping[str, Any] | None,
        raw_call: Callable[[], RawChat],
    ) -> ChatResult:
        key = LLMCache.key(self.cache_namespace, task, kind, inputs)
        t0 = time.perf_counter()
        usage: dict[str, Any] = {}
        try:
            text: str | None = None
            parsed: Any | None = None
            hit = False
            cached = self._cache.get(key) if self._cache else None
            if cached is not None:
                # A malformed or schema-violating entry is a miss; it is overwritten below.
                try:
                    cand = cached["response"]["text"]
                    if isinstance(cand, str):
                        parsed = self._validate(task, cand, schema)
                        text = cand
                        usage = dict(cached.get("usage") or {})
                        hit = True
                except (KeyError, TypeError, ValueError, ProviderOutputError):
                    text = None
            if text is None:
                raw = raw_call()
                text = raw.text
                usage = {
                    "prompt_tokens": raw.prompt_tokens,
                    "completion_tokens": raw.completion_tokens,
                }
                parsed = self._validate(task, text, schema)
                if self._cache:
                    self._cache.put(
                        key,
                        {
                            "kind": str(kind),
                            "provider": self.ref.provider,
                            "model": self.ref.model,
                            "task": str(task),
                            "response": {"text": text},
                            "usage": usage,
                        },
                    )
        except Exception as exc:
            err = self._err(task, exc)
            self._emit(task, kind, key, t0, cached=False, error=str(err))
            if err is exc:
                raise
            raise err from exc
        entry = self._emit(task, kind, key, t0, cached=hit, usage=usage)
        return ChatResult(text=text, parsed=parsed, log=entry)

    # -- public ----------------------------------------------------------
    def chat(
        self,
        task: Task,
        messages: Sequence[Message],
        *,
        json_schema: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        inputs = {
            "messages": [m.model_dump(mode="json") for m in messages],
            "json_schema": json_schema,
        }
        return self._text_call(
            task,
            CallKind.chat,
            inputs,
            json_schema,
            lambda: self._chat_raw(task, messages, json_schema, TEMPERATURE),
        )

    def vision(
        self,
        task: Task,
        image_bytes: bytes,
        prompt: str,
        *,
        json_schema: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        """A schema, when given, validates the reply (a failure is never cached) and is part of
        the cache key; without one the key is the pre-schema key (existing caches stay valid)."""
        inputs: dict[str, Any] = {"image_sha256": sha256_hex(image_bytes), "prompt": prompt}
        if json_schema is None:
            return self._text_call(
                task,
                CallKind.vision,
                inputs,
                None,
                lambda: self._vision_raw(task, image_bytes, prompt, TEMPERATURE),
            )
        inputs["json_schema"] = json_schema
        return self._text_call(
            task,
            CallKind.vision,
            inputs,
            json_schema,
            lambda: self._vision_raw(
                task, image_bytes, prompt, TEMPERATURE, json_schema=json_schema
            ),
        )

    def embed(self, task: Task, texts: Sequence[str]) -> list[list[float]]:
        key = LLMCache.key(self.cache_namespace, task, CallKind.embed, {"texts": list(texts)})
        t0 = time.perf_counter()
        try:
            vectors: list[list[float]] | None = None
            usage: dict[str, Any] = {}
            hit = False
            cached = self._cache.get(key) if self._cache else None
            if cached is not None:
                try:
                    vectors = self._check_vectors(
                        task, cached["response"]["vectors"], len(texts), round_values=False
                    )
                    usage = dict(cached.get("usage") or {})
                    hit = True
                except (KeyError, TypeError, ValueError, ProviderError):
                    vectors = None
            if vectors is None:
                raw = self._embed_raw(task, texts)
                vectors = self._check_vectors(task, raw.vectors, len(texts), round_values=True)
                usage = {"prompt_tokens": raw.prompt_tokens, "completion_tokens": None}
                if self._cache:
                    self._cache.put(
                        key,
                        {
                            "kind": str(CallKind.embed),
                            "provider": self.ref.provider,
                            "model": self.ref.model,
                            "task": str(task),
                            "response": {"vectors": vectors},
                            "usage": usage,
                        },
                    )
        except Exception as exc:
            err = self._err(task, exc)
            self._emit(task, CallKind.embed, key, t0, cached=False, error=str(err))
            if err is exc:
                raise
            raise err from exc
        self._emit(task, CallKind.embed, key, t0, cached=hit, usage=usage)
        return vectors


@dataclass(frozen=True)
class ProviderSet:
    by_task: Mapping[Task, Provider] = field(default_factory=dict)

    def get(self, task: Task) -> Provider:
        p = self.by_task.get(task)
        if p is None:
            raise ProviderError(f"no provider configured for task {task}", task=task)
        return p


Factory = Callable[[ModelRef, LogSink, LLMCache | None, Clock], Provider]


def _mock_factory(ref: ModelRef, sink: LogSink, cache: LLMCache | None, clock: Clock) -> Provider:
    from manuallabor.providers.mock import MockProvider

    return MockProvider(ref, sink=sink, cache=cache, clock=clock)


DEFAULT_FACTORIES: Mapping[str, Factory] = {"mock": _mock_factory}


def build_provider_set(
    config: ProjectConfig,
    *,
    cache_dir: Path | None,
    sink: LogSink,
    factories: Mapping[str, Factory] = DEFAULT_FACTORIES,
    clock: Clock = utc_now,
) -> ProviderSet:
    cache = LLMCache(cache_dir) if cache_dir is not None else None
    by_task: dict[Task, Provider] = {}
    for task in Task:
        ref = config.model_for(task)
        if ref is None:
            continue
        factory = factories.get(ref.provider)
        if factory is None:
            raise ProviderError(
                f"unknown provider {ref.provider!r} for task {task}",
                provider=ref.provider,
                model=ref.model,
                task=task,
            )
        by_task[task] = factory(ref, sink, cache, clock)
    return ProviderSet(by_task=by_task)
