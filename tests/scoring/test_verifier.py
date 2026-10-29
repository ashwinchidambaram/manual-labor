"""Test 17: the optional llm_verifier is a strictly validated second reader."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from manuallabor.contracts.config import ModelRef, ProjectConfig, TaskModels
from manuallabor.contracts.enums import SignalName, Task
from manuallabor.contracts.llm import Message
from manuallabor.providers import ListSink, MockProvider, ProviderError, ProviderSet
from manuallabor.providers.base import RawChat
from manuallabor.providers.cache import LLMCache
from manuallabor.scoring.pipeline import score_block
from manuallabor.scoring.verifier import (
    llm_verifier,
    plan_verifier,
    validate_answer,
    verifier_messages,
)
from tests.scoring.conftest import ctx, make_block

CLEANUP = ModelRef(provider="mock", model="mock-1")
VERIFIER = ModelRef(provider="mock", model="mock-verifier")
RAW = "Tighten the cover\nbolts in a cross pattern."
CLEAN = "Tighten the cover bolts in a cross pattern."


class SpyProvider(MockProvider):
    temperatures: list[float]

    def __init__(self, **kw: Any) -> None:
        super().__init__(VERIFIER, **kw)
        self.temperatures = []

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self.temperatures.append(temperature)
        return super()._chat_raw(task, messages, json_schema, temperature)


def _config(verifier: ModelRef | None) -> ProjectConfig:
    return ProjectConfig(name="p", models=TaskModels(cleanup=CLEANUP, verifier=verifier))


def _plan(
    reply: str | None, tmp_path: Path, verifier: ModelRef | None = VERIFIER, raise_err: bool = False
):  # type: ignore[no-untyped-def]
    sink = ListSink()
    responses: dict[Task, Any] = {}
    if reply is not None:
        responses[Task.verifier] = reply
    if raise_err:

        def boom(_m: Sequence[Message]) -> str:
            raise ProviderError("down")

        responses[Task.verifier] = boom
    prov = SpyProvider(sink=sink, cache=LLMCache(tmp_path / ".llm_cache"), responses=responses)
    return (
        plan_verifier(_config(verifier), lambda: ProviderSet(by_task={Task.verifier: prov})),
        prov,
        sink,
    )


def test_skip_reasons(tmp_path: Path) -> None:
    plan, prov, sink = _plan("NONE", tmp_path)
    assert llm_verifier(RAW, None, faith_passed=True, plan=plan) == ("skip_no_clean", None)
    assert llm_verifier(RAW, RAW, faith_passed=True, plan=plan) == ("skip_unchanged", None)
    assert llm_verifier(RAW, CLEAN, faith_passed=False, plan=plan) == ("skip_faith_failed", None)
    no, _, _ = _plan("NONE", tmp_path, verifier=None)
    assert llm_verifier(RAW, CLEAN, faith_passed=True, plan=no) == ("skip_no_verifier", None)
    # TaskModels now rejects verifier == cleanup, so the guard is reached with an unvalidated
    # config (a hand-built or legacy one); the pipeline must still skip, not self-grade
    with pytest.raises(ValueError, match="verifier must differ from cleanup"):
        _config(CLEANUP)
    unchecked = ProjectConfig(name="p").model_copy(
        update={"models": TaskModels.model_construct(cleanup=CLEANUP, verifier=CLEANUP)}
    )
    same = plan_verifier(unchecked, lambda: ProviderSet(by_task={}))
    assert llm_verifier(RAW, CLEAN, faith_passed=True, plan=same) == ("skip_same_model", None)
    assert sink == []  # none of the skips called a model


def test_none_answer(tmp_path: Path) -> None:
    """NONE is no evidence of correctness: it contributes no signal (a 1.0 soft signal would
    raise the geometric mean and could lift a block over the threshold)."""
    plan, prov, sink = _plan("NONE.", tmp_path)
    outcome, s = llm_verifier(RAW, CLEAN, faith_passed=True, plan=plan)
    assert outcome == "ok" and s is None
    assert prov.temperatures == [0.0]
    # second identical call is served from the cache
    llm_verifier(RAW, CLEAN, faith_passed=True, plan=plan)
    assert [e.cached for e in sink] == [False, True]
    assert prov.temperatures == [0.0]


def test_valid_span_flags(tmp_path: Path) -> None:
    plan, _, _ = _plan("`cross pattern`", tmp_path)
    outcome, s = llm_verifier(RAW, CLEAN, faith_passed=True, plan=plan)
    assert outcome == "flag" and s is not None and s.value == 0.2 and not s.critical
    assert s.detail == "verifier: 'cross pattern'"


@pytest.mark.parametrize(
    "reply",
    [
        "The cleaned text changes the torque value.",  # not a span of either text
        "Tighten " * 50,  # > 300 chars
        "Tighten the cover\n\nbolts",  # blank line
        "",
        "   ",
        "None of the facts changed, but",
    ],
)
def test_invalid_answers_omitted(reply: str) -> None:
    outcome, s = validate_answer(reply, RAW, CLEAN)
    assert outcome == "verifier_invalid" and s is None


def test_provider_error_omitted(tmp_path: Path) -> None:
    plan, _, sink = _plan(None, tmp_path, raise_err=True)
    assert llm_verifier(RAW, CLEAN, faith_passed=True, plan=plan) == ("verifier_errors", None)
    assert len(sink) == 1 and not sink[0].ok


def test_score_block_counts_and_never_asks_about_failed_cleanup(tmp_path: Path) -> None:
    plan, prov, sink = _plan("cross", tmp_path)
    counters: Counter[str] = Counter()
    b = make_block(RAW, clean_text=CLEAN)
    s = score_block(b, ctx(), threshold=0.85, plan=plan, counters=counters)
    v = next(x for x in s.signals if x.name == SignalName.llm_verifier)
    assert v.value == 0.2 and counters["flag"] == 1
    bad = make_block(RAW, clean_text=CLEAN.replace("cross", "star"))
    s = score_block(bad, ctx(), threshold=0.85, plan=plan, counters=counters)
    assert all(x.name != SignalName.llm_verifier for x in s.signals)
    assert counters["skip_faith_failed"] == 1 and len(sink) == 1


def test_prompt_is_a_second_read_not_a_rating() -> None:
    m = verifier_messages(RAW, CLEAN)
    assert [x.role for x in m] == ["system", "user"]
    assert m[1].content == (
        f"<raw>{RAW}</raw>\n<clean>{CLEAN}</clean>\n"
        "Does the cleaned text change any fact, number, or step? "
        "Answer with the differing span or NONE"
    )
    assert "confiden" not in (m[0].content + m[1].content).lower()
    assert "rate" not in (m[0].content + m[1].content).lower()


def test_progress_detail_counts() -> None:
    from manuallabor.scoring.pipeline import _detail

    c: Counter[str] = Counter(
        {
            "ok": 2,
            "flag": 1,
            "verifier_invalid": 3,
            "verifier_errors": 1,
            "skip_same_model": 4,
            "skip_no_clean": 9,
            "parser_agreement unavailable: ocr_alt": 5,
        }
    )
    assert _detail(c) == (
        "verifier_flagged: 1; verifier_ok: 2; parser_agreement unavailable: ocr_alt: 5; "
        "verifier_errors: 1; verifier_invalid: 3; verifier skipped: 4"
    )
    assert _detail(Counter({"skip_no_clean": 3})) is None


@pytest.mark.parametrize("reply", ["e", ".", "the", "The", "a", "in", "`.`", "'e'", "of the", "--"])
def test_weak_answers_ignored(reply: str) -> None:
    """Spans under 3 chars, punctuation, or bare function words are not a differing span."""
    outcome, s = validate_answer(reply, RAW, CLEAN)
    assert outcome == "verifier_invalid" and s is None


def test_span_must_be_in_raw_or_clean() -> None:
    assert validate_answer("star pattern", RAW, CLEAN) == ("verifier_invalid", None)
    outcome, s = validate_answer("cover bolts", RAW, CLEAN)
    assert outcome == "flag" and s is not None and s.value == 0.2


def _soft_block():  # type: ignore[no-untyped-def]
    """A cleaned block whose soft signals put it just under the threshold (0.8486...)."""
    from manuallabor.contracts.block import OcrWord

    words = [
        OcrWord(text=w, confidence=c, bbox=[0, 0, 1, 1])
        for w, c in zip(RAW.split(), [0.62, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8], strict=True)
    ]
    texts = {"ocr": RAW, "ocr_alt": RAW}
    return make_block(RAW, source="ocr", texts=texts, ocr_words=words, clean_text=CLEAN)


@pytest.mark.parametrize("reply", ["NONE", "none.", "e", ".", "the"])
def test_verifier_never_raises_a_block_over_threshold(tmp_path: Path, reply: str) -> None:
    """Reviewer's case: 0.8486 without the verifier became 0.8842 with a NONE answer (a 1.0
    soft signal diluting the soft mean) and was auto-approved. NONE and weak answers must
    leave the score unchanged."""
    b = _soft_block()
    base = score_block(b, ctx(n_columns=2), threshold=0.85)
    assert base.confidence is not None and 0.80 < base.confidence < 0.85, base.signals
    assert base.status == "queued"
    plan, _, _ = _plan(reply, tmp_path)
    s = score_block(b, ctx(n_columns=2), threshold=0.85, plan=plan)
    assert all(x.name != SignalName.llm_verifier for x in s.signals)
    assert s.confidence == base.confidence and s.status == "queued"


def test_found_span_lowers_score(tmp_path: Path) -> None:
    b = _soft_block()
    base = score_block(b, ctx(n_columns=2), threshold=0.85)
    plan, _, _ = _plan("cross pattern", tmp_path)
    s = score_block(b, ctx(n_columns=2), threshold=0.85, plan=plan)
    assert s.confidence is not None and base.confidence is not None
    assert s.confidence < base.confidence
