"""Backend table, endpoint resolution and factory registration. Imports nothing heavy."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Literal

from manuallabor.contracts.config import ModelRef
from manuallabor.providers.base import Clock, Factory, LogSink, Provider, ProviderError
from manuallabor.providers.cache import LLMCache

OLLAMA_DEFAULT = "http://localhost:11434"
SchemaMode = Literal["native", "prompt"]


@dataclass(frozen=True)
class BackendSpec:
    name: str
    chat_id: str  # format string with {m}
    embed_id: str | None
    default_base: str | None
    base_env: str | None
    key_env: str | None
    key_required: bool
    base_required: bool
    schema_mode: SchemaMode
    max_concurrency: int
    read_timeout: float


_OPENAI = BackendSpec(
    name="openai",
    chat_id="openai/{m}",
    embed_id="openai/{m}",
    default_base=None,
    base_env="OPENAI_BASE_URL",
    key_env="OPENAI_API_KEY",
    key_required=True,
    base_required=False,
    schema_mode="native",
    max_concurrency=4,
    read_timeout=120.0,
)
_LOCAL_OPENAI = BackendSpec(
    name="vllm",
    chat_id="openai/{m}",
    embed_id="openai/{m}",
    default_base=None,
    base_env=None,
    key_env=None,
    key_required=False,
    base_required=True,
    schema_mode="native",
    max_concurrency=1,
    read_timeout=600.0,
)

SPECS: dict[str, BackendSpec] = {
    "ollama": BackendSpec(
        name="ollama",
        chat_id="ollama_chat/{m}",
        embed_id="ollama/{m}",
        default_base=OLLAMA_DEFAULT,
        base_env="OLLAMA_HOST",
        key_env=None,
        key_required=False,
        base_required=False,
        schema_mode="native",
        max_concurrency=1,
        read_timeout=600.0,
    ),
    "anthropic": BackendSpec(
        name="anthropic",
        chat_id="anthropic/{m}",
        embed_id=None,
        default_base=None,
        base_env=None,
        key_env="ANTHROPIC_API_KEY",
        key_required=True,
        base_required=False,
        schema_mode="prompt",
        max_concurrency=4,
        read_timeout=120.0,
    ),
    "openai": _OPENAI,
    "openai_compatible": BackendSpec(**{**_OPENAI.__dict__, "name": "openai_compatible"}),
    "vllm": _LOCAL_OPENAI,
    "llamacpp": BackendSpec(**{**_LOCAL_OPENAI.__dict__, "name": "llamacpp"}),
}


@dataclass(frozen=True)
class Endpoint:
    """Resolved connection data. The key is read from the environment at resolution time and
    is deliberately excluded from repr."""

    api_base: str | None
    api_key: str | None

    def __repr__(self) -> str:
        return f"Endpoint(api_base={self.api_base!r}, api_key={'***' if self.api_key else None})"


def normalize_ollama_host(value: str | None) -> str:
    v = (value or "").strip()
    if not v:
        return OLLAMA_DEFAULT
    if not re.match(r"^https?://", v):
        v = "http://" + v
    scheme, rest = v.split("://", 1)
    rest = rest.rstrip("/")
    hostport, sep, path = rest.partition("/")
    host, colon, port = hostport.partition(":")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    if not colon and scheme == "http" and not sep:
        port = "11434"
        colon = ":"
    return f"{scheme}://{host}{colon}{port}{sep}{path}".rstrip("/")


def resolve_endpoint(
    ref: ModelRef, env: Mapping[str, str] | None = None, spec: BackendSpec | None = None
) -> Endpoint:
    env = os.environ if env is None else env
    spec = spec or SPECS.get(ref.provider)
    if spec is None:
        raise ProviderError(
            f"unknown provider {ref.provider!r}", provider=ref.provider, model=ref.model
        )
    base = ref.api_base or (env.get(spec.base_env) if spec.base_env else None) or spec.default_base
    if spec.name == "ollama":
        base = normalize_ollama_host(base)
    if spec.base_required and not base:
        raise ProviderError(
            f"provider {spec.name!r} requires api_base in the model reference",
            provider=ref.provider,
            model=ref.model,
        )
    key_env = ref.api_key_env or spec.key_env
    key = env.get(key_env) if key_env else None
    if spec.key_required and not key and not (spec.name.startswith("openai") and base):
        raise ProviderError(
            f"environment variable {key_env} is not set (required for provider {spec.name!r})",
            provider=ref.provider,
            model=ref.model,
            retriable=False,
        )
    if not key and not spec.key_required and spec.name != "ollama":
        key = "not-needed"
    if not key and spec.name.startswith("openai"):
        key = "not-needed"
    return Endpoint(api_base=base, api_key=key)


def make_factory(name: str) -> Factory:
    def factory(ref: ModelRef, sink: LogSink, cache: LLMCache | None, clock: Clock) -> Provider:
        from manuallabor.providers.litellm_provider import LiteLLMProvider

        spec = SPECS[name]
        endpoint = resolve_endpoint(ref, spec=spec)
        return LiteLLMProvider(
            ref, sink=sink, cache=cache, clock=clock, spec=spec, endpoint=endpoint
        )

    return factory


def register_defaults(factories: MutableMapping[str, Factory]) -> None:
    for name in SPECS:
        factories.setdefault(name, make_factory(name))
