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
CLEAN = "Tighten the cover bolts in a cross pattern."  # whitespace-only cleanup of RAW
# a pair whose canonical tokens differ: the verifier has something to point at
NRAW = "Tighten the cover\nbolts to 35 N·m in a cross pattern."
NCLEAN = "Tighten the cover bolts to 53 N·m in a cross pattern."
# an evidence-backed reorder: faithfulness passes (0.9) and the tokens differ
RRAW = "Tighten the cover\nbolts in a cross pattern.\nCheck the seal."
RCLEAN = "Check the seal. Tighten the cover bolts in a cross pattern."
RALT = "Check the seal.\nTighten the cover\nbolts in a cross pattern."
# build/human-test, b-pump-service-tables-p002-07: a whitespace-only cleanup and the recorded
# qwen2.5:1.5b reply, which copies the whole passage back
P002_07_RAW = (
    "Do not operate the unit while the wiring harness is removed. Replace the drive belt if it "
    "shows any sign of\ndeformation. Rotate the pressure valve through 90° until it seats fully."
)
P002_07_CLEAN = (
    "Do not operate the unit while the wiring harness is removed. Replace the drive belt if it "
    "shows any sign of deformation. Rotate the pressure valve through 90° until it seats fully."
)
P002_07_REPLY = P002_07_CLEAN
# build/human-test, b-pump-service-tables-p001-05: cleanup only added GFM pipes and a separator
TABLE_RAW = (
    "Component | Fastener | Torque | Grade\nCover plate | M8 | 35 N·m | 8.8\n"
    "Mounting bracket | M10 | 48 N·m | 8.8"
)
TABLE_CLEAN = (
    "| Component | Fastener | Torque | Grade |\n|---|---|---|---|\n"
    "| Cover plate | M8 | 35 N·m | 8.8 |\n| Mounting bracket | M10 | 48 N·m | 8.8 |"
)
TABLE_REPLY = "| Component | Fastener | Torque | Grade |"


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
    assert llm_verifier(RAW, CLEAN, faith_passed=True, plan=plan) == ("skip_unchanged", None)
    assert llm_verifier(NRAW, NCLEAN, faith_passed=False, plan=plan) == ("skip_faith_failed", None)
    no, _, _ = _plan("NONE", tmp_path, verifier=None)
    assert llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=no) == ("skip_no_verifier", None)
    # TaskModels now rejects verifier == cleanup, so the guard is reached with an unvalidated
    # config (a hand-built or legacy one); the pipeline must still skip, not self-grade
    with pytest.raises(ValueError, match="verifier must differ from cleanup"):
        _config(CLEANUP)
    unchecked = ProjectConfig(name="p").model_copy(
        update={"models": TaskModels.model_construct(cleanup=CLEANUP, verifier=CLEANUP)}
    )
    same = plan_verifier(unchecked, lambda: ProviderSet(by_task={}))
    assert llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=same) == ("skip_same_model", None)
    assert sink == []  # none of the skips called a model


def test_none_answer(tmp_path: Path) -> None:
    """NONE is no evidence of correctness: it contributes no signal (a 1.0 soft signal would
    raise the geometric mean and could lift a block over the threshold)."""
    plan, prov, sink = _plan("NONE.", tmp_path)
    outcome, s = llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=plan)
    assert outcome == "ok" and s is None
    assert prov.temperatures == [0.0]
    # second identical call is served from the cache
    llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=plan)
    assert [e.cached for e in sink] == [False, True]
    assert prov.temperatures == [0.0]


def test_valid_span_flags(tmp_path: Path) -> None:
    """Positive control: cleanup turned 35 N·m into 53 N·m and the verifier quotes the clean
    side. The flag keeps VERIFIER_FLAG_VALUE and its detail carries the raw and clean
    fragments that differ, so the panel can show the evidence next to the verdict."""
    plan, _, _ = _plan("`53 N·m`", tmp_path)
    outcome, s = llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=plan)
    assert outcome == "flag" and s is not None and s.value == 0.2 and not s.critical
    assert s.detail == 'verifier quoted "53 N·m"; raw "35" -> clean "53"'


@pytest.mark.parametrize("reply", ["35 N·m", "to 35", "53", "35", "bolts to 53 N·m in a"])
def test_span_on_either_side_of_the_change_flags(reply: str) -> None:
    outcome, s = validate_answer(reply, NRAW, NCLEAN)
    assert outcome == "flag" and s is not None and s.value == 0.2
    assert s.detail is not None and s.detail.endswith('raw "35" -> clean "53"')


@pytest.mark.parametrize("reply", ["cross pattern", "Tighten the cover bolts", "N·m in a cross"])
def test_span_outside_the_change_is_no_evidence(reply: str) -> None:
    """Verbatim in both versions but nowhere near the place where they differ: no flag."""
    assert validate_answer(reply, NRAW, NCLEAN) == ("verifier_invalid", None)


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
    outcome, s = validate_answer(reply, NRAW, NCLEAN)
    assert outcome == "verifier_invalid" and s is None


def test_provider_error_omitted(tmp_path: Path) -> None:
    plan, _, sink = _plan(None, tmp_path, raise_err=True)
    assert llm_verifier(NRAW, NCLEAN, faith_passed=True, plan=plan) == ("verifier_errors", None)
    assert len(sink) == 1 and not sink[0].ok


def test_score_block_counts_and_never_asks_about_failed_cleanup(tmp_path: Path) -> None:
    plan, prov, sink = _plan("seal", tmp_path)
    counters: Counter[str] = Counter()
    texts = {"pymupdf": RALT, "docling": RALT}
    b = make_block(RRAW, texts=texts, clean_text=RCLEAN)
    s = score_block(b, ctx(), threshold=0.85, plan=plan, counters=counters)
    v = next(x for x in s.signals if x.name == SignalName.llm_verifier)
    assert v.value == 0.2 and counters["flag"] == 1
    bad = make_block(RRAW, texts=texts, clean_text=RCLEAN.replace("cross", "star"))
    s = score_block(bad, ctx(), threshold=0.85, plan=plan, counters=counters)
    assert all(x.name != SignalName.llm_verifier for x in s.signals)
    assert counters["skip_faith_failed"] == 1 and len(sink) == 1


def test_score_block_never_calls_the_verifier_on_a_whitespace_only_cleanup(
    tmp_path: Path,
) -> None:
    """118 of 124 calls in build/human-test were on pairs that differ only in whitespace; the
    model was asked to find a difference that does not exist."""
    plan, prov, sink = _plan("cover bolts", tmp_path)
    counters: Counter[str] = Counter()
    s = score_block(
        make_block(RAW, clean_text=CLEAN), ctx(), threshold=0.85, plan=plan, counters=counters
    )
    assert all(x.name != SignalName.llm_verifier for x in s.signals)
    assert counters["skip_unchanged"] == 1
    assert sink == [] and prov.temperatures == []


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
    outcome, s = validate_answer(reply, NRAW, NCLEAN)
    assert outcome == "verifier_invalid" and s is None


def test_span_must_be_in_raw_or_clean_and_mark_a_change() -> None:
    """Inverted (2026-10-30): RAW and CLEAN differ only by a newline, so "cover bolts" marks no
    change; it used to flag at 0.2. A span found unchanged in both versions is no evidence."""
    assert validate_answer("star pattern", RAW, CLEAN) == ("verifier_invalid", None)
    assert validate_answer("cover bolts", RAW, CLEAN) == ("verifier_invalid", None)
    assert validate_answer("star pattern", NRAW, NCLEAN) == ("verifier_invalid", None)


def test_replay_p002_07_whole_passage_copied_back_does_not_flag(tmp_path: Path) -> None:
    """The recorded reply of build/human-test b-pump-service-tables-p002-07 was scored 0.2: the
    model copied the passage back and the passage is verbatim in both versions."""
    assert validate_answer(P002_07_REPLY, P002_07_RAW, P002_07_CLEAN) == (
        "verifier_invalid",
        None,
    )
    plan, prov, sink = _plan(P002_07_REPLY, tmp_path)
    assert llm_verifier(P002_07_RAW, P002_07_CLEAN, faith_passed=True, plan=plan) == (
        "skip_unchanged",
        None,
    )
    assert sink == [] and prov.temperatures == []


def test_table_with_only_pipes_added_does_not_flag(tmp_path: Path) -> None:
    """build/human-test b-pump-service-tables-p001-05: the recorded reply quoted the header row
    the cleanup had only wrapped in pipes."""
    from manuallabor.contracts.enums import BlockType

    assert validate_answer(TABLE_REPLY, TABLE_RAW, TABLE_CLEAN) == ("verifier_invalid", None)
    assert validate_answer("Cover plate | M8", TABLE_RAW, TABLE_CLEAN) == ("verifier_invalid", None)
    plan, prov, sink = _plan(TABLE_REPLY, tmp_path)
    got = llm_verifier(
        TABLE_RAW, TABLE_CLEAN, faith_passed=True, plan=plan, block_type=BlockType.table
    )
    assert got == ("skip_unchanged", None)
    assert sink == [] and prov.temperatures == []


def test_table_cell_change_still_flags() -> None:
    clean = TABLE_CLEAN.replace("48 N·m", "84 N·m")
    outcome, s = validate_answer("84 N·m", TABLE_RAW, clean)
    assert outcome == "flag" and s is not None and s.value == 0.2
    assert s.detail == 'verifier quoted "84 N·m"; raw "48" -> clean "84"'


def test_header_removed_by_cleanup_is_not_a_change(tmp_path: Path) -> None:
    """AE3: a known header line that cleanup removed is an allowed edit; the token comparison
    uses the same canonicalisation as the faithfulness check, so it is not a difference."""
    raw = "Acme X200 Service Manual\nTighten the cover\nbolts in a cross pattern."
    plan, prov, sink = _plan("Acme X200 Service Manual", tmp_path)
    got = llm_verifier(
        raw, CLEAN, faith_passed=True, plan=plan, hf_strings=["Acme X200 Service Manual"]
    )
    assert got == ("skip_unchanged", None) and sink == []


def test_evidence_fragments_are_bounded_and_parseable() -> None:
    """The detail stays within DETAIL_MAX without cutting a quoted fragment: each fragment is a
    JSON string literal, so the panel can read it back exactly."""
    import json
    import re

    from manuallabor.scoring.types import DETAIL_MAX

    long_raw = "Use the " + " ".join(f"w{i}" for i in range(80)) + ' "quoted" part.'
    long_clean = "Use the " + " ".join(f"v{i}" for i in range(80)) + ' "quoted" part.'
    outcome, s = validate_answer("Use the v0 v1 v2", long_raw, long_clean)
    assert outcome == "flag" and s is not None and s.detail is not None
    assert len(s.detail) <= DETAIL_MAX
    lits = re.findall(r'"(?:[^"\\]|\\.)*"', s.detail)
    assert len(lits) == 3
    span, raw_frag, clean_frag = (json.loads(x) for x in lits)
    assert span == "Use the v0 v1 v2"
    assert raw_frag.startswith("w0 w1") and raw_frag.endswith("…")
    assert clean_frag.startswith("v0 v1") and clean_frag.endswith("…")


def _soft_block():  # type: ignore[no-untyped-def]
    """A cleaned block just under the threshold (0.8427...) whose cleanup changed tokens: an
    evidence-backed reorder (both OCR readings saw the clean order), so the verifier is asked."""
    from manuallabor.contracts.block import OcrWord

    ws = RRAW.split()
    words = [
        OcrWord(text=w, confidence=c, bbox=[0, 0, 1, 1])
        for w, c in zip(ws, [0.85] + [0.95] * (len(ws) - 1), strict=True)
    ]
    texts = {"ocr": RALT, "ocr_alt": RALT}
    return make_block(RRAW, source="ocr", texts=texts, ocr_words=words, clean_text=RCLEAN)


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
    plan, _, _ = _plan("Check the seal.", tmp_path)
    s = score_block(b, ctx(n_columns=2), threshold=0.85, plan=plan)
    assert s.confidence is not None and base.confidence is not None
    assert s.confidence < base.confidence
    v = next(x for x in s.signals if x.name == SignalName.llm_verifier)
    assert v.value == 0.2


def test_span_in_the_unmoved_part_of_a_reorder_does_not_lower_score(tmp_path: Path) -> None:
    b = _soft_block()
    base = score_block(b, ctx(n_columns=2), threshold=0.85)
    plan, _, sink = _plan("cross pattern", tmp_path)
    s = score_block(b, ctx(n_columns=2), threshold=0.85, plan=plan)
    assert len(sink) == 1  # the verifier was asked: the tokens differ
    assert all(x.name != SignalName.llm_verifier for x in s.signals)
    assert s.confidence == base.confidence
