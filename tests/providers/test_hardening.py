"""Module-6 review fixes: truncation guards, max_tokens budget, error paths."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import respx

from manuallabor.contracts import Message, ModelRef, Task
from manuallabor.providers import ListSink, LLMCache, ProviderError
from manuallabor.providers.base import Provider, utc_now
from manuallabor.providers.litellm_provider import OLLAMA_NUM_CTX
from manuallabor.providers.registry import make_factory
from tests.providers.contract.conftest import PNG, SECRET, Replay

HOSTS = {
    "ollama": ("ollama", "localhost", "llama3.2:1b", None),
    "anthropic": ("anthropic", "api.anthropic.com", "claude-haiku-4-5", None),
    "openai": ("openai", "api.openai.com", "gpt-x", None),
    "vllm": ("openai", "127.0.0.1", "m", "http://127.0.0.1:8000/v1"),
}

Build = Callable[..., tuple[Provider, Replay, ListSink, Path]]


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Build]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    stack: list[respx.MockRouter] = []

    def make(name: str) -> tuple[Provider, Replay, ListSink, Path]:
        fmt, host, model, base = HOSTS[name]
        r = Replay(fmt)
        router = respx.mock(assert_all_mocked=True, assert_all_called=False)
        router.start()
        stack.append(router)
        router.route(host=host).mock(side_effect=r.handler)
        sink = ListSink()
        cache_dir = tmp_path / "cache"
        ref = ModelRef(provider=name, model=model, api_base=base)
        p = make_factory(name)(ref, sink, LLMCache(cache_dir), utc_now)
        p._sleep = lambda s: None  # type: ignore[attr-defined]
        return p, r, sink, cache_dir

    yield make
    for router in stack:
        router.stop()


def user(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


def cached_files(cache_dir: Path) -> list[Path]:
    return list(cache_dir.glob("*.json")) if cache_dir.exists() else []


# -- item 2: truncated replies --------------------------------------------------
@pytest.mark.parametrize("name", list(HOSTS))
def test_truncated_reply_is_an_error_and_not_cached(name: str, build: Build) -> None:
    p, r, sink, cache_dir = build(name)
    r.script("length")
    with pytest.raises(ProviderError, match="response truncated at max_tokens") as ei:
        p.chat(Task.cleanup, user("hello"))
    assert ei.value.retriable is False
    assert len(r.inference) == 1
    assert cached_files(cache_dir) == []
    assert sink[-1].ok is False and sink[-1].truncated is True
    assert p.chat(Task.cleanup, user("hello")).text  # recovered, asks again


def test_non_truncated_error_is_not_flagged(build: Build) -> None:
    p, r, sink, _ = build("openai")
    r.script("empty")
    with pytest.raises(ProviderError):
        p.chat(Task.cleanup, user("x"))
    assert sink[-1].truncated is False


def _predict(r: Replay, i: int = 0) -> int:
    b = r.inference[i].body
    return int(b["options"]["num_predict"] if r.fmt == "ollama" else b["max_tokens"])


@pytest.mark.parametrize("name", ["ollama", "openai"])
def test_cleanup_max_tokens_scales_with_input(name: str, build: Build) -> None:
    p, r, _, _ = build(name)
    r.prompt_tokens = 6000  # Ollama replays: a realistic count for the large prompts below
    p.chat(Task.cleanup, user("short"))
    assert 256 < _predict(r, 0) < 300
    text = "word " * 1500 * 3  # about 1500 tokens of 3.5 chars/token... a 1,500-token block
    p.chat(Task.cleanup, user(text))
    n_in = len(text) / 3.5
    assert _predict(r, 1) >= 2 * 1500 + 256 or _predict(r, 1) >= int(2 * n_in) + 256 - 8
    p.chat(Task.cleanup, user("word " * 3000))  # huge input: capped
    assert _predict(r, 2) == 4096


def test_other_tasks_keep_fixed_budget(build: Build) -> None:
    p, r, _, _ = build("openai")
    p.chat(Task.verifier, user("x" * 100))
    assert _predict(r) == 256


# -- item 1: Ollama prompt truncation -------------------------------------------
def test_oversize_prompt_raises_before_any_request(build: Build) -> None:
    p, r, sink, cache_dir = build("ollama")
    text = "step tighten bolt. " * 2000  # ~38k chars, about 10.8k estimated tokens
    with pytest.raises(ProviderError, match="prompt truncated") as ei:
        p.chat(Task.cleanup, user(text))
    assert ei.value.retriable is False
    assert r.inference == []
    assert cached_files(cache_dir) == []
    assert sink[-1].ok is False


def test_prompt_eval_count_far_below_estimate_raises(build: Build) -> None:
    """The reviewer's case: ~8.4k-token prompt, Ollama reported prompt_eval_count=4098."""
    p, r, _, cache_dir = build("ollama")
    r.prompt_tokens = 4098
    text = "step tighten bolt. " * 1450  # ~27.5k chars -> estimate ~7.9k < num_ctx
    with pytest.raises(ProviderError, match="prompt truncated") as ei:
        p.chat(Task.verifier, user(text))
    assert ei.value.retriable is False
    assert len(r.inference) == 1
    assert cached_files(cache_dir) == []


def test_normal_prompt_with_small_count_is_fine(build: Build) -> None:
    p, r, _, _ = build("ollama")
    assert p.chat(Task.cleanup, user("Reply ok")).log.prompt_tokens == 12
    assert OLLAMA_NUM_CTX == 8192


def test_num_ctx_is_sent_in_options(build: Build) -> None:
    p, r, _, _ = build("ollama")
    p.chat(Task.cleanup, user("hi"))
    assert r.inference[0].body["options"]["num_ctx"] == OLLAMA_NUM_CTX


# -- minor (a): the estimated flag is per call -----------------------------------
def test_estimated_flag_resets_between_calls(build: Build) -> None:
    p, r, _, cache_dir = build("openai")
    r.drop_usage = True
    p.chat(Task.cleanup, user("first prompt"))  # estimated
    r.drop_usage = False
    p.embed(Task.embeddings, ["alpha", "beta", "gamma"])  # must not inherit the flag
    emb = [json.loads(f.read_text()) for f in cache_dir.glob("*.json")]
    embed_entries = [e for e in emb if e["kind"] == "embed"]
    assert embed_entries and "estimated" not in embed_entries[0]["usage"]


# -- item 5: error paths ----------------------------------------------------------
def test_ollama_404_has_pull_hint(build: Build) -> None:
    p, r, _, _ = build("ollama")
    r.script("http_404")
    with pytest.raises(ProviderError, match=r"ollama pull llama3\.2:1b") as ei:
        p.chat(Task.cleanup, user("x"))
    assert ei.value.retriable is False
    assert len(r.inference) == 1


def test_empty_string_embed_rejected_for_ollama(build: Build) -> None:
    p, r, _, _ = build("ollama")
    with pytest.raises(ProviderError, match="empty string"):
        p.embed(Task.embeddings, ["ok", "  "])
    assert r.inference == []


def test_embed_batches_over_64(build: Build) -> None:
    p, r, _, _ = build("openai")
    texts = [f"t{i}" for i in range(130)]
    # the recorded reply has 3 vectors per call, so the count check fails; the point is batching
    with pytest.raises(ProviderError, match="expected 130 vectors"):
        p.embed(Task.embeddings, texts)
    sizes = [len(c.body["input"]) for c in r.inference]
    assert sizes == [64, 64, 2]


def test_unsupported_image_type(build: Build) -> None:
    p, r, _, _ = build("openai")
    with pytest.raises(ProviderError, match="unsupported image format"):
        p.vision(Task.vision, b"BM not a supported image", "describe")
    assert r.inference == []
    assert p.vision(Task.vision, PNG, "describe").text


def test_http_429_retries_then_errors(build: Build) -> None:
    p, r, sink, _ = build("openai")
    r.script("http_429", "http_429", "http_429")
    with pytest.raises(ProviderError) as ei:
        p.chat(Task.cleanup, user("x"))
    assert ei.value.retriable is True
    assert len(r.inference) == 3
    assert sink[-1].ok is False


def test_http_429_then_ok(build: Build) -> None:
    p, r, _, _ = build("openai")
    r.script("http_429")
    assert p.chat(Task.cleanup, user("x")).text
    assert len(r.inference) == 2


@pytest.mark.parametrize("name", ["ollama", "openai"])
def test_malformed_response_is_a_provider_error(name: str, build: Build) -> None:
    p, r, _, cache_dir = build(name)
    r.script("malformed", "malformed", "malformed")
    with pytest.raises(ProviderError):
        p.chat(Task.cleanup, user("x"))
    assert len(r.inference) == 3  # LiteLLM reports a garbled body as a retriable error
    assert cached_files(cache_dir) == []


def test_unfence() -> None:
    from manuallabor.providers.litellm_provider import _unfence

    assert _unfence('```json\n{"n": 1}\n```') == '{"n": 1}'
    assert _unfence('```\n{"n": 1}\n```') == '{"n": 1}'
    assert _unfence('  ```JSON \n{"n": 1}```  ') == '{"n": 1}'
    assert _unfence('{"n": 1}') == '{"n": 1}'
    assert _unfence("plain ``` text") == "plain ``` text"


def _any(x: Any) -> Any:
    return x


# -- item 3: the verifier is a different model than cleanup -------------------------
def test_default_verifier_differs_from_cleanup() -> None:
    from manuallabor.contracts import TaskModels

    m = TaskModels()
    assert m.verifier is not None
    assert (m.verifier.provider, m.verifier.model) == ("ollama", "qwen2.5:1.5b")
    assert (m.cleanup.provider, m.cleanup.model) != (m.verifier.provider, m.verifier.model)


def test_verifier_equal_to_cleanup_is_rejected() -> None:
    from pydantic import ValidationError

    from manuallabor.contracts import TaskModels

    ref = ModelRef(provider="ollama", model="llama3.2:1b")
    with pytest.raises(ValidationError, match="verifier must differ from cleanup"):
        TaskModels(cleanup=ref, verifier=ModelRef(provider="ollama", model="llama3.2:1b"))
    TaskModels(cleanup=ref, verifier=None)  # no verifier is fine
    TaskModels(cleanup=ref, verifier=ModelRef(provider="ollama", model="qwen2.5:1.5b"))
    TaskModels(cleanup=ref, verifier=ModelRef(provider="anthropic", model="llama3.2:1b"))


@pytest.mark.parametrize("tier", ["small", "medium", "large", "api"])
def test_every_tier_has_a_distinct_verifier(tier: str) -> None:
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    table = pr.suggest(ps.mac_probe())
    chosen = pr.tier_models(table, tier)  # type: ignore[arg-type]
    assert chosen["verifier"] != chosen["cleanup"]
    if tier == "small":
        assert chosen["verifier"] == {"provider": "ollama", "model": "qwen2.5:1.5b"}


@pytest.mark.parametrize("tier", ["small", "medium", "large", "api"])
def test_apply_tier_output_satisfies_the_validator(tier: str, tmp_path: Path) -> None:
    from manuallabor.contracts import ProjectConfig
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    cfg = tmp_path / "project.json"
    cfg.write_text(json.dumps({"name": "p"}))
    probe = ps.mac_probe(ram_bytes=128 * 1024**3, brand="Apple M3 Max", disk=500.0)
    pr.apply_tier(cfg, pr.suggest(probe), tier, probe=probe)  # type: ignore[arg-type]
    c = ProjectConfig.model_validate_json(cfg.read_text())
    assert c.models.verifier is not None
    assert (c.models.verifier.provider, c.models.verifier.model) != (
        c.models.cleanup.provider,
        c.models.cleanup.model,
    )


# -- minors -----------------------------------------------------------------------------
def _project_json(tmp_path: Path, **extra: Any) -> Path:
    cfg = tmp_path / "project.json"
    cfg.write_text(
        json.dumps(
            {
                "name": "p",
                "models": {
                    "metadata": {"provider": "ollama", "model": "custom-meta"},
                    "agent": {"provider": "anthropic", "model": "claude-opus-x"},
                },
                **extra,
            }
        )
    )
    return cfg


def test_apply_tier_resets_metadata_and_agent_unless_kept(tmp_path: Path) -> None:
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    probe = ps.mac_probe()
    table = pr.suggest(probe)
    cfg = _project_json(tmp_path)
    pr.apply_tier(cfg, table, "small", probe=probe)
    models = json.loads(cfg.read_text())["models"]
    assert models["metadata"] is None and models["agent"] is None
    cfg = _project_json(tmp_path)
    pr.apply_tier(cfg, table, "small", probe=probe, keep_overrides=True)
    models = json.loads(cfg.read_text())["models"]
    assert (
        models["metadata"]["model"] == "custom-meta" and models["agent"]["model"] == "claude-opus-x"
    )


def test_apply_refuses_when_total_memory_exceeds_budget(tmp_path: Path) -> None:
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    # 16 GB M3: each medium model fits alone, but the five together (~12 GB) do not
    probe = ps.mac_probe()
    table = pr.suggest(probe)
    cfg = _project_json(tmp_path)
    before = cfg.read_bytes()
    with pytest.raises(pr.ApplyError, match="memory"):
        pr.apply_tier(cfg, table, "medium", probe=probe)
    assert cfg.read_bytes() == before
    pr.apply_tier(cfg, table, "medium", probe=probe, force=True)
    pr.apply_tier(cfg, table, "small", probe=probe)  # the reference machine takes small


def test_apply_refuses_when_pulls_exceed_free_disk(tmp_path: Path) -> None:
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    probe = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max", disk=3.0)
    table = pr.suggest(probe)
    cfg = _project_json(tmp_path)
    with pytest.raises(pr.ApplyError, match="disk"):
        pr.apply_tier(cfg, table, "large", probe=probe)
    pr.apply_tier(cfg, table, "large", probe=probe, force=True)
    pr.apply_tier(cfg, table, "api", probe=probe)  # nothing to pull


def test_8gb_machine_with_nothing_fitting_suggests_api() -> None:
    from manuallabor.providers import probe as pr
    from tests.providers import probe_support as ps

    probe = ps.linux_probe({}, ram_kb=8 * 1024 * 1024)
    table = pr.suggest(probe)
    assert table.default_tier == "api"
    assert table.default_reason and "no local tier fits" in table.default_reason
    text = pr.render_table(probe, table)
    assert "Suggested tier: api" in text and "no local tier fits" in text
    assert pr.suggest(ps.mac_probe()).default_reason is None


def test_parse_ollama_tags_tolerates_bad_sizes() -> None:
    from manuallabor.providers import probe as pr

    raw = json.dumps(
        {
            "models": [
                {"name": "neg", "size": -5, "digest": "a"},
                {"name": "huge", "size": 1e999, "digest": "b"},
                {"name": "nan", "size": "NaN", "digest": "c"},
                {"name": "ok", "size": 1073741824, "digest": "d"},
            ]
        }
    ).replace("1e999", "Infinity")
    got = {m.name: m.size_gb for m in pr.parse_ollama_tags(raw)}
    assert got == {"neg": None, "huge": None, "nan": None, "ok": 1.0}


def test_litellm_env_is_forced_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from manuallabor.providers import litellm_provider as lp

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    monkeypatch.setenv("LITELLM_TELEMETRY", "True")
    lp._litellm.cache_clear()
    lp._litellm()
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert os.environ["LITELLM_TELEMETRY"] == "False"


def test_probe_missing_project_dir_errors(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from manuallabor.cli import app

    missing = tmp_path / "nope"
    res = CliRunner().invoke(app, ["probe", "--project", str(missing)])
    assert res.exit_code == 2
    assert "not found" in res.output
    assert not missing.exists()


def test_ollama_api_base_restored_after_call(build: Build, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setenv("OLLAMA_API_BASE", "http://elsewhere:1")
    p, r, _, _ = build("ollama")
    p.chat(Task.cleanup, user("hi"))
    assert os.environ.get("OLLAMA_API_BASE") == "http://elsewhere:1"
    monkeypatch.delenv("OLLAMA_API_BASE")
    p.embed(Task.embeddings, ["a", "b", "c"])
    assert "OLLAMA_API_BASE" not in os.environ
