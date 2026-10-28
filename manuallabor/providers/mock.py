"""Deterministic mock providers for tests and `labor check`."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from manuallabor.contracts.config import ModelRef
from manuallabor.contracts.enums import Task
from manuallabor.contracts.llm import Message
from manuallabor.providers.base import (
    RAW_CLOSE,
    RAW_OPEN,
    BaseProvider,
    Clock,
    LogSink,
    ProviderError,
    RawChat,
    RawEmbed,
    utc_now,
)
from manuallabor.providers.cache import LLMCache

Responder = Callable[[Sequence[Message]], str]


def echo_cleanup(messages: Sequence[Message]) -> str:
    users = [m for m in messages if m.role == "user"]
    content = users[-1].content if users else (messages[-1].content if messages else "")
    start = content.rfind(RAW_OPEN)
    if start != -1:
        body_start = start + len(RAW_OPEN)
        end = content.find(RAW_CLOSE, body_start)
        if end != -1:
            return content[body_start:end]
    return content


DEFAULT_MOCK_RESPONSES: dict[Task, str | Responder] = {
    Task.cleanup: echo_cleanup,
    Task.verifier: "NONE",
    Task.metadata: '{"title": null, "product_model": null}',
}


def nfkd_ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def hashed_embedding(text: str, dim: int = 256) -> list[float]:
    v = [0.0] * dim
    for tok in re.findall(r"[a-z0-9]+", nfkd_ascii(text).lower()):
        h = hashlib.sha256(tok.encode()).digest()
        v[int.from_bytes(h[:4], "big") % dim] += 1.0 if h[4] % 2 == 0 else -1.0
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        v[0] = 1.0
        return v
    return [round(x / norm, 6) + 0.0 for x in v]


class MockProvider(BaseProvider):
    def __init__(
        self,
        ref: ModelRef | None = None,
        *,
        sink: LogSink,
        cache: LLMCache | None = None,
        clock: Clock = utc_now,
        responses: Mapping[Task, str | Responder] | None = None,
        vision_response: Callable[[bytes, str], str] | None = None,
        dim: int = 256,
    ) -> None:
        super().__init__(
            ref or ModelRef(provider="mock", model="mock-1"), sink=sink, cache=cache, clock=clock
        )
        self.responses: dict[Task, str | Responder] = dict(responses or {})
        self.vision_response = vision_response
        self.dim = dim

    def _replies_digest(self) -> str:
        """sha256 over the canned replies (and the vision responder), so that two mocks with
        the same ModelRef but different replies never share cache entries."""

        def describe(v: str | Responder | Callable[[bytes, str], str] | None) -> str:
            if v is None:
                return "none"
            if isinstance(v, str):
                return "str:" + v
            code = getattr(v, "__code__", None)
            body = (
                code.co_code.hex() + re.sub(r"0x[0-9a-f]+", "", repr(code.co_consts))
                if code is not None
                else ""
            )
            return f"fn:{getattr(v, '__module__', '')}.{getattr(v, '__qualname__', repr(v))}:{body}"

        merged = {**DEFAULT_MOCK_RESPONSES, **self.responses}
        parts = {str(t): describe(merged[t]) for t in sorted(merged, key=str)}
        parts["vision"] = describe(self.vision_response)
        parts["dim"] = str(self.dim)
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    @property
    def cache_namespace(self) -> str:
        return (
            f"{self.ref.provider}:{self.ref.model}:{type(self).__name__}:{self._replies_digest()}"
        )

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        resp = self.responses.get(task, DEFAULT_MOCK_RESPONSES.get(task))
        if resp is None:
            raise ProviderError(
                f"mock: no response for task {task}",
                provider=self.ref.provider,
                model=self.ref.model,
                task=task,
            )
        text = resp(messages) if callable(resp) else resp
        prompt = " ".join(m.content for m in messages)
        return RawChat(text, len(prompt.split()), len(text.split()))

    def _vision_raw(
        self, task: Task, image_bytes: bytes, prompt: str, temperature: float
    ) -> RawChat:
        if self.vision_response is not None:
            text = self.vision_response(image_bytes, prompt)
        else:
            digest = hashlib.sha256(image_bytes).hexdigest()[:8]
            text = f"Generated description (mock) of image {digest}."
        return RawChat(text, len(prompt.split()), len(text.split()))

    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        return RawEmbed(
            [hashed_embedding(t, self.dim) for t in texts],
            sum(len(t.split()) for t in texts),
        )


CorruptMode = Literal["digit", "insert", "delete"]
CORRUPT_CYCLE: tuple[CorruptMode, ...] = ("digit", "insert", "delete")


def corrupt(text: str, mode: CorruptMode = "digit") -> str:
    """Return text that always differs from the input (pure)."""
    if mode == "delete":
        tokens = list(re.finditer(r"\S+", text))
        if not tokens:
            return "not"
        start, end = tokens[-1].span()
        trailing = len(text[end:]) - len(text[end:].lstrip())
        if trailing:
            end += trailing
        else:
            start -= len(text[:start]) - len(text[:start].rstrip())
        return text[:start] + text[end:]
    if mode == "digit":
        m = re.search(r"[0-9]", text)
        if m is not None:
            d = int(m.group())
            return text[: m.start()] + str((d + 1) % 10) + text[m.end() :]
    if not text.strip():
        return "not"
    tokens = list(re.finditer(r"\S+", text))
    if len(tokens) == 1:
        return text + " not"
    s = tokens[1].start()
    return text[:s] + "not " + text[s:]


class CorruptingMockProvider(MockProvider):
    """Cleanup output is always corrupted. Uses a distinct model name so that
    its cache entries never collide with MockProvider's in a shared cache dir.

    mode=None cycles digit -> insert -> delete, one step per (uncached) cleanup call."""

    def __init__(
        self,
        ref: ModelRef | None = None,
        *,
        mode: CorruptMode | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(ref or ModelRef(provider="mock", model="mock-corrupt-1"), **kwargs)
        self.mode: CorruptMode | None = mode
        self._calls = 0
        user_cleanup = self.responses.get(Task.cleanup, echo_cleanup)

        def _cleanup(messages: Sequence[Message]) -> str:
            base = user_cleanup(messages) if callable(user_cleanup) else user_cleanup
            mode = self.mode if self.mode is not None else CORRUPT_CYCLE[self._calls % 3]
            self._calls += 1
            return corrupt(base, mode)

        self.responses[Task.cleanup] = _cleanup
        self._user_cleanup = user_cleanup

    @property
    def cache_namespace(self) -> str:
        wrapper = self.responses[Task.cleanup]
        self.responses[Task.cleanup] = self._user_cleanup
        try:
            inner = super()._replies_digest()
        finally:
            self.responses[Task.cleanup] = wrapper
        base_digest = hashlib.sha256((inner + repr(self.mode)).encode()).hexdigest()
        return f"{self.ref.provider}:{self.ref.model}:{type(self).__name__}:{base_digest}"
