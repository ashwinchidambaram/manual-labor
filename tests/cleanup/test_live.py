"""Test 40: live cleanup + descriptions against a local Ollama model. Skips cleanly unless
MANUALLABOR_LIVE=1 and Ollama serves the model. The provider is test-local until module 6
registers a real `ollama` provider. Never run beside another Docling/LLM process (16 GB)."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from manuallabor.cleanup.describe import describe_figure
from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.types import LLM_TYPES
from manuallabor.contracts import ModelRef, Task
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import read_json
from manuallabor.contracts.llm import Message
from manuallabor.providers import ListSink, ProviderError
from manuallabor.providers.base import BaseProvider, RawChat, RawEmbed
from manuallabor.providers.cache import LLMCache
from tests.cleanup.test_gt import independent_check

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = "gemma4:e4b-it-q4_K_M"
LIMIT = int(os.environ.get("MANUALLABOR_LIVE_LIMIT", "20"))


class OllamaTestProvider(BaseProvider):
    def _post(self, payload: dict[str, Any]) -> RawChat:
        body = json.dumps({**payload, "model": self.ref.model, "stream": False}).encode()
        req = urllib.request.Request(
            f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return RawChat(
            data["message"]["content"], data.get("prompt_eval_count"), data.get("eval_count")
        )

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        payload: dict[str, Any] = {
            "messages": [m.model_dump(mode="json") for m in messages],
            "options": {"temperature": temperature},
        }
        if json_schema is not None:
            payload["format"] = dict(json_schema)
        return self._post(payload)

    def _vision_raw(
        self,
        task: Task,
        image_bytes: bytes,
        prompt: str,
        temperature: float,
        json_schema: Mapping[str, Any] | None = None,
    ) -> RawChat:
        msg = {
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(image_bytes).decode()],
        }
        payload: dict[str, Any] = {"messages": [msg], "options": {"temperature": temperature}}
        if json_schema is not None:
            payload["format"] = dict(json_schema)
        return self._post(payload)

    def _embed_raw(self, task: Task, texts: Sequence[str]) -> RawEmbed:
        raise ProviderError("chat/vision-only test provider")


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as resp:  # noqa: S310
            names = [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        return False
    return MODEL in names


LIVE = os.environ.get("MANUALLABOR_LIVE") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE or not _ollama_ready(),
    reason="set MANUALLABOR_LIVE=1 and serve " + MODEL + " from Ollama at " + OLLAMA,
)


def test_40_live_cleanup_and_describe(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    proj = request.getfixturevalue("groupedproj")
    slug = "clean"
    sink = ListSink()
    prov = OllamaTestProvider(
        ModelRef(provider="ollama", model=MODEL), sink=sink, cache=LLMCache(tmp_path / "cache")
    )
    raw = proj.raw_blocks(slug)
    eligible = [
        b
        for b in sorted(raw, key=lambda b: b.reading_order)
        if b.type in LLM_TYPES and b.raw_text.strip()
    ][:LIMIT]
    entries, _ = clean_document(
        proj.doc(slug),
        raw,
        proj.layouts(slug),
        {b.id for b in eligible},
        mode="always",
        provider=prov,
        cleanup_ref=f"ollama:{MODEL}",
    )
    ctxs = proj.contexts(slug)
    by_id = {b.id: b for b in raw}
    outcomes: Counter[str] = Counter()
    reaching = 0
    for e in entries:
        assert e.llm is not None
        outcomes[e.llm.outcome if e.llm.outcome != "rejected" else f"rejected:{e.llm.reason}"] += 1
        b = by_id[e.block_id].model_copy(update={"clean_text": e.clean_text})
        reaching += len(independent_check(b, ctxs[b.id]))
    print(f"\nLIVE {MODEL}: {len(entries)} LLM cleanups: {dict(sorted(outcomes.items()))}")
    print(f"LIVE: faithfulness violations reaching clean_text: {reaching}")
    assert reaching == 0
    # describe 3 figures
    figs = [b for b in raw if b.figure_id][:3]
    for b in figs:
        assert b.figure_id is not None
        rec = read_json(proj.paths.figure_file(slug, b.figure_id, "json"), FigureRecord)
        png = (proj.paths.figure_dir(slug) / rec.file).resolve().read_bytes()
        d = describe_figure(prov, png, rec.caption_original)
        print(f"LIVE describe {b.figure_id}: {d.outcome} {d.description!r} {d.tags}")
        if d.outcome == "ok":
            assert d.description is not None and len(d.description) <= 300
            assert len(d.tags) <= 8
        else:
            assert d.outcome in ("invalid", "error") and d.description is None
