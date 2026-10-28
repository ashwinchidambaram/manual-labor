from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from manuallabor.contracts import CallKind, Message, ModelRef, ProjectConfig, Task
from manuallabor.contracts.io import canonical_json
from manuallabor.providers import (
    TEMPERATURE,
    CorruptingMockProvider,
    JsonlSink,
    ListSink,
    LLMCache,
    MockProvider,
    ProviderError,
    ProviderOutputError,
    ProviderSet,
    build_provider_set,
    corrupt,
)
from manuallabor.providers.base import RawChat

TEXTS = ["Tighten the M8 bolts to 35 N·m", "wiring diagram for the 12 V fuse box", "belt tension"]


def user(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def make(tmp: Path | None, sink: ListSink, **kw: Any) -> MockProvider:
    return MockProvider(sink=sink, cache=LLMCache(tmp / "cache") if tmp else None, **kw)


def test_p1_embed_deterministic_and_pinned() -> None:
    a = MockProvider(sink=ListSink()).embed(Task.embeddings, TEXTS)
    b = MockProvider(sink=ListSink()).embed(Task.embeddings, TEXTS)
    assert a == b
    assert hashlib.sha256(canonical_json(a)).hexdigest() == PINNED_EMBED_SHA


PINNED_EMBED_SHA = "98cb9a90a7c735b40f75b1ae92a8eb66755fb8977631cc5955e74f323b94af42"


def test_p2_cosine() -> None:
    v = MockProvider(sink=ListSink()).embed(
        Task.embeddings,
        [
            "Tighten the M8 bolts to 35 N·m",
            "tighten M8 bolts to 35 N·m",
            "wiring diagram for the 12 V fuse box",
        ],
    )
    assert cos(v[0], v[1]) > 0.7
    assert cos(v[0], v[2]) < 0.4


def test_p3_dim_norm_zero() -> None:
    v = MockProvider(sink=ListSink()).embed(Task.embeddings, TEXTS + ["", "···"])
    for vec in v[:3]:
        assert len(vec) == 256
        assert abs(math.sqrt(sum(x * x for x in vec)) - 1) < 1e-5
    e0 = [1.0] + [0.0] * 255
    assert v[3] == e0 and v[4] == e0


def test_p4_cleanup_echo() -> None:
    p = MockProvider(sink=ListSink())
    msgs = [
        Message(role="system", content="<raw>no</raw>"),
        Message(role="user", content="first <raw>old</raw> then <raw>the text\nline</raw> tail"),
    ]
    assert p.chat(Task.cleanup, msgs).text == "the text\nline"
    assert p.chat(Task.cleanup, user("plain")).text == "plain"
    assert p.chat(Task.verifier, user("x")).text == "NONE"


def test_p5_canned() -> None:
    p = MockProvider(
        sink=ListSink(),
        responses={
            Task.grouping: "canned",
            Task.agent: lambda m: f"saw {m[-1].content}",
        },
    )
    assert p.chat(Task.grouping, user("q")).text == "canned"
    assert p.chat(Task.agent, user("q")).text == "saw q"


def test_p6_no_response() -> None:
    with pytest.raises(ProviderError, match="grouping"):
        MockProvider(sink=ListSink()).chat(Task.grouping, user("q"))


SCHEMA = {
    "type": "object",
    "properties": {"n": {"type": "integer"}},
    "required": ["n"],
    "additionalProperties": False,
}


def test_p7_json_schema(tmp_path: Path) -> None:
    sink = ListSink()
    ok = make(tmp_path, sink, responses={Task.grouping: '{"n": 3}'})
    r = ok.chat(Task.grouping, user("q"), json_schema=SCHEMA)
    assert r.parsed == {"n": 3}
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1
    for i, body in enumerate(["not json", '{"n": "x"}', '{"n": 1, "z": 2}']):
        d = tmp_path / f"c{i}"
        p = MockProvider(sink=sink, cache=LLMCache(d), responses={Task.grouping: body})
        with pytest.raises(ProviderOutputError) as ei:
            p.chat(Task.grouping, user("q"), json_schema=SCHEMA)
        assert ei.value.raw_text == body
        assert not d.exists() or list(d.glob("*.json")) == []
    assert sink[-1].ok is False


def test_p8_one_log_per_call(tmp_path: Path) -> None:
    sink = ListSink()
    p = make(tmp_path, sink, responses={Task.grouping: "bad"})
    p.chat(Task.cleanup, user("<raw>a</raw>"))
    p.chat(Task.cleanup, user("<raw>a</raw>"))
    p.vision(Task.vision, b"img", "describe")
    p.vision(Task.vision, b"img", "describe")
    p.embed(Task.embeddings, ["a", "b"])
    p.embed(Task.embeddings, ["a", "b"])
    with pytest.raises(ProviderOutputError):
        p.chat(Task.grouping, user("q"), json_schema=SCHEMA)
    assert len(sink) == 7
    kinds = [(x.kind, x.cached, x.ok) for x in sink]
    assert kinds == [
        (CallKind.chat, False, True),
        (CallKind.chat, True, True),
        (CallKind.vision, False, True),
        (CallKind.vision, True, True),
        (CallKind.embed, False, True),
        (CallKind.embed, True, True),
        (CallKind.chat, False, False),
    ]
    assert all(x.provider == "mock" and x.model == "mock-1" for x in sink)
    assert [x.task for x in sink][:2] == [Task.cleanup] * 2
    key = LLMCache.key(
        "mock",
        "mock-1",
        Task.cleanup,
        "chat",
        {"messages": [{"role": "user", "content": "<raw>a</raw>"}], "json_schema": None},
    )
    assert sink[0].input_hash == sink[1].input_hash == key
    assert (tmp_path / "cache" / f"{key}.json").exists()
    assert sink[-1].error and "JSON" in sink[-1].error
    assert sink[0].prompt_tokens == 1 and sink[0].completion_tokens == 1


class Spy(MockProvider):
    temps: list[float]

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self.temps.append(temperature)
        return super()._chat_raw(task, messages, json_schema, temperature)

    def _vision_raw(
        self, task: Task, image_bytes: bytes, prompt: str, temperature: float
    ) -> RawChat:
        self.temps.append(temperature)
        return super()._vision_raw(task, image_bytes, prompt, temperature)


def test_p9_temperature_zero() -> None:
    p = Spy(sink=ListSink())
    p.temps = []
    p.chat(Task.cleanup, user("a"))
    p.vision(Task.vision, b"x", "p")
    assert p.temps == [0.0, 0.0] and TEMPERATURE == 0.0


@given(st.text())
def test_p10_corrupt_never_equal(text: str) -> None:
    for mode in ("digit", "insert_word"):
        assert corrupt(text, mode) != text  # type: ignore[arg-type]


@given(st.text(alphabet="abc 9\t5x", min_size=0, max_size=30))
def test_p10_corrupt_shapes(text: str) -> None:
    out = corrupt(text, "digit")
    if any(ch in "0123456789" for ch in text):
        assert len(out) == len(text)
        diffs = [(a, b) for a, b in zip(text, out, strict=True) if a != b]
        assert len(diffs) == 1 and diffs[0][0].isdigit() and diffs[0][1].isdigit()
    ins = corrupt(text, "insert_word")
    assert len(ins.split()) == len(text.split()) + 1
    assert sorted(ins.split()) == sorted([*text.split(), "not"])


def test_p10_corrupting_provider() -> None:
    p = CorruptingMockProvider(sink=ListSink())
    assert p.chat(Task.cleanup, user("<raw>set 5 bolts</raw>")).text == "set 6 bolts"
    q = CorruptingMockProvider(sink=ListSink(), mode="insert_word")
    assert q.chat(Task.cleanup, user("<raw>set 5 bolts</raw>")).text == "set not 5 bolts"
    assert p.ref.model != MockProvider(sink=ListSink()).ref.model


def test_p11_vision() -> None:
    p = MockProvider(sink=ListSink())
    a = p.vision(Task.vision, b"abc", "describe").text
    assert a == p.vision(Task.vision, b"abc", "describe").text
    assert a != p.vision(Task.vision, b"abd", "describe").text
    assert a == f"Generated description (mock) of image {hashlib.sha256(b'abc').hexdigest()[:8]}."


def test_p12_build_provider_set(mock_config: ProjectConfig, tmp_path: Path) -> None:
    sink = ListSink()
    ps = build_provider_set(mock_config, cache_dir=tmp_path / "c", sink=sink)
    assert set(ps.by_task) == set(Task)
    assert all(isinstance(p, MockProvider) for p in ps.by_task.values())
    cfg = ProjectConfig.model_validate(
        {"name": "x", "models": {"cleanup": {"provider": "nope", "model": "m"}}}
    )
    with pytest.raises(ProviderError, match="nope"):
        build_provider_set(cfg, cache_dir=None, sink=sink)
    cfg2 = mock_config.model_copy(deep=True)
    cfg2.models.verifier = None
    ps2 = build_provider_set(cfg2, cache_dir=None, sink=sink)
    with pytest.raises(ProviderError):
        ps2.get(Task.verifier)
    assert ps2.get(Task.cleanup) is ps2.by_task[Task.cleanup]
    assert isinstance(ps2, ProviderSet)


def test_p12b_conftest_fixtures(
    mock_providers: ProviderSet, corrupting_providers: ProviderSet, call_log: ListSink
) -> None:
    assert mock_providers.get(Task.cleanup).chat(Task.cleanup, user("<raw>7</raw>")).text == "7"
    assert (
        corrupting_providers.get(Task.cleanup).chat(Task.cleanup, user("<raw>7</raw>")).text == "8"
    )
    assert call_log[0].timestamp.year == 2026


def test_k1_key() -> None:
    k = LLMCache.key
    base = k("p", "m", "cleanup", "chat", {"messages": [{"a": 1, "b": 2}], "json_schema": None})
    assert base == k(
        "p", "m", "cleanup", "chat", {"json_schema": None, "messages": [{"b": 2, "a": 1}]}
    )
    variants = [
        k("p2", "m", "cleanup", "chat", {"messages": [{"a": 1, "b": 2}], "json_schema": None}),
        k("p", "m2", "cleanup", "chat", {"messages": [{"a": 1, "b": 2}], "json_schema": None}),
        k("p", "m", "grouping", "chat", {"messages": [{"a": 1, "b": 2}], "json_schema": None}),
        k("p", "m", "cleanup", "vision", {"messages": [{"a": 1, "b": 2}], "json_schema": None}),
        k("p", "m", "cleanup", "chat", {"messages": [{"a": 1, "b": 3}], "json_schema": None}),
        k("p", "m", "cleanup", "chat", {"messages": [{"a": 1, "b": 2}], "json_schema": {}}),
    ]
    assert len({base, *variants}) == 7
    s = ListSink()
    p = MockProvider(sink=s)
    p.vision(Task.vision, b"a", "x")
    p.vision(Task.vision, b"b", "x")
    assert s[0].input_hash != s[1].input_hash


class Counting(MockProvider):
    calls = 0

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self.calls += 1
        return super()._chat_raw(task, messages, json_schema, temperature)


def test_k2_hit(tmp_path: Path) -> None:
    sink = ListSink()
    p = Counting(sink=sink, cache=LLMCache(tmp_path))
    r1 = p.chat(Task.cleanup, user("<raw>a b</raw>"))
    r2 = p.chat(Task.cleanup, user("<raw>a b</raw>"))
    assert p.calls == 1
    assert (r1.text, r1.parsed) == (r2.text, r2.parsed)
    assert r2.log.cached is True and sink[1].cached is True and r1.log.cached is False
    # second provider instance, same cache: still a hit
    q = Counting(sink=sink, cache=LLMCache(tmp_path))
    q.chat(Task.cleanup, user("<raw>a b</raw>"))
    assert q.calls == 0
    v = p.embed(Task.embeddings, ["x y"])
    assert v == p.embed(Task.embeddings, ["x y"])


def test_k3_file_layout(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "c")
    entry = {
        "kind": "chat",
        "provider": "p",
        "model": "m",
        "task": "cleanup",
        "response": {"text": "é"},
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    cache.put("k" * 64, entry)
    f = tmp_path / "c" / f"{'k' * 64}.json"
    first = f.read_bytes()
    cache.put("k" * 64, entry)
    assert f.read_bytes() == first
    assert list((tmp_path / "c").glob("*.tmp")) == []
    assert json.loads(first)["key"] == "k" * 64
    assert "é".encode() in first


def test_k4_truncated(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    p = Counting(sink=ListSink(), cache=LLMCache(tmp_path))
    p.chat(Task.cleanup, user("<raw>abc</raw>"))
    f = next(tmp_path.glob("*.json"))
    good = f.read_text()
    f.write_text(good[: len(good) // 2])
    with caplog.at_level("WARNING"):
        r = p.chat(Task.cleanup, user("<raw>abc</raw>"))
    assert p.calls == 2 and r.text == "abc"
    assert f.read_text() == good
    assert any("miss" in rec.message for rec in caplog.records)
    # wrong key inside file -> miss
    d = json.loads(good)
    d["key"] = "z" * 64
    f.write_text(json.dumps(d))
    p.chat(Task.cleanup, user("<raw>abc</raw>"))
    assert p.calls == 3


def test_k5_no_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = MockProvider(sink=ListSink(), cache=None)
    p.chat(Task.cleanup, user("a"))
    p.embed(Task.embeddings, ["a"])
    p.vision(Task.vision, b"a", "b")
    assert list(tmp_path.iterdir()) == []


def test_k6_raw_error(tmp_path: Path) -> None:
    class Boom(MockProvider):
        def _chat_raw(self, *a: Any, **k: Any) -> RawChat:
            raise RuntimeError("kaput")

    sink = ListSink()
    p = Boom(sink=sink, cache=LLMCache(tmp_path / "c"))
    with pytest.raises(ProviderError, match="kaput") as ei:
        p.chat(Task.cleanup, user("x"))
    assert ei.value.retriable is False and ei.value.task == Task.cleanup
    assert not (tmp_path / "c").exists() or list((tmp_path / "c").iterdir()) == []
    assert len(sink) == 1 and sink[0].ok is False and "kaput" in (sink[0].error or "")


def test_k7_jsonl_sink(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "llm_calls.jsonl"
    p = MockProvider(sink=JsonlSink(path))
    p.chat(Task.cleanup, user("a"))
    p.embed(Task.embeddings, ["é"])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for ln in lines:
        d = json.loads(ln)
        assert ln == json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert d["provider"] == "mock"
        assert ", " not in ln and ": " not in ln
    assert ModelRef(provider="mock", model="mock-1")
