"""Live check against a local Ollama `nomic-embed-text` (design test 36). Skips cleanly unless
MANUALLABOR_LIVE=1 and the model answers. The embedder is test-local until module 6 registers
a real `ollama` provider."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from manuallabor.contracts import ModelRef, Task
from manuallabor.contracts.enums import BlockType
from manuallabor.grouping.pipeline import check_partition, group_document
from manuallabor.grouping.types import default_params, embed_prefix_for
from manuallabor.providers import ListSink, ProviderError
from manuallabor.providers.base import BaseProvider, RawChat, RawEmbed
from tests.grouping.conftest import gt_blocks, gt_document, provider_set

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = "nomic-embed-text"


class OllamaEmbedTestProvider(BaseProvider):
    def _chat_raw(
        self, task: Task, messages: Any, json_schema: Mapping[str, Any] | None, temperature: float
    ) -> RawChat:
        raise ProviderError("embedding-only test provider")

    def _vision_raw(
        self, task: Task, image_bytes: bytes, prompt: str, temperature: float
    ) -> RawChat:
        raise ProviderError("embedding-only test provider")

    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        body = json.dumps({"model": self.ref.model, "input": list(texts)}).encode()
        req = urllib.request.Request(
            f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return RawEmbed(data["embeddings"])


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as resp:  # noqa: S310
            names = [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        return False
    return any(n.split(":")[0] == MODEL for n in names)


@pytest.mark.skipif(os.environ.get("MANUALLABOR_LIVE") != "1", reason="set MANUALLABOR_LIVE=1")
@pytest.mark.parametrize("name", ["clean", "twocol"])
def test_live_nomic_topics(name: str) -> None:
    if not _ollama_ready():
        pytest.skip(f"Ollama with {MODEL} is not reachable at {OLLAMA}")
    blocks = gt_blocks(name)
    sink = ListSink()
    emb = OllamaEmbedTestProvider(ModelRef(provider="ollama", model=MODEL), sink=sink, cache=None)
    ps = provider_set(sink, embeddings=emb)
    params = default_params(embed_prefix_for(MODEL))
    gf = group_document(gt_document(name, blocks), blocks, ps, params=params)
    assert gf.topic_status == "ok", gf.topic_error
    assert check_partition(blocks, gf) == []
    topics = [t for t in gf.topics if not t.is_unassigned]
    n_body = sum(1 for b in blocks if b.type not in (BlockType.header, BlockType.footer))
    cohesions = [t.cohesion for t in topics]
    print(f"\nLIVE {name}: n={n_body} topics={len(topics)} t000={gf.topics[0].block_count}")
    print(f"LIVE {name}: cohesion min={min(cohesions):.3f} max={max(cohesions):.3f}")  # type: ignore[type-var]
    assert all(c is not None and 0.0 <= c <= 1.0 for c in cohesions)
    assert 3 <= len(topics) <= n_body // 4
