"""Tests 11-15: the candidate chain, residual triggers, the LLM prompt and output validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from manuallabor.cleanup import rules
from manuallabor.cleanup.lexicon import Lexicon
from manuallabor.cleanup.llm import SYSTEM_PROMPT, validate_output
from manuallabor.cleanup.pipeline import clean_document
from manuallabor.cleanup.residual import residual_reasons
from manuallabor.cleanup.rules import DetResult, Pass, PassCtx, compose, plan_passes
from manuallabor.cleanup.types import fallback_detail
from manuallabor.cleanup.verify import clean_block
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType, Task
from manuallabor.contracts.llm import Message
from manuallabor.providers import ListSink, MockProvider, ProviderError
from manuallabor.providers.base import RawChat
from manuallabor.providers.cache import LLMCache
from manuallabor.scoring.faithfulness import FaithOutcome, check_faithfulness_ex
from manuallabor.scoring.pipeline import faith_kwargs, score_block
from manuallabor.scoring.types import BlockContext
from tests.cleanup.conftest import doc_of, mk

H = "0" * 64
P = BlockType.paragraph


def bctx(**kw: Any) -> BlockContext:
    base: dict[str, Any] = {"parser_versions": {"pymupdf": "x", "docling": "y"}}
    base.update(kw)
    return BlockContext(**base)


def run(
    b: Block,
    *,
    ctx: BlockContext | None = None,
    provider: Any = None,
    mode: str = "residual",
    passes: Sequence[Pass] | None = None,
    lexicon: Lexicon | None = None,
    prefilter: bool = True,
) -> Any:
    c = ctx or bctx()
    pctx = PassCtx(block_type=b.type, page=b.page, lexicon=lexicon or Lexicon(), table=b.table)
    return clean_block(
        b,
        c,
        input_hash=H,
        passes=passes if passes is not None else plan_passes(b.type, b.table is not None),
        pctx=pctx,
        mode=mode,  # type: ignore[arg-type]
        provider=provider,
        prefilter=prefilter,
    )


# -- 11 fallback chain ----------------------------------------------------------------------


def _bad(text: str, ctx: PassCtx) -> str:
    return text + " X"  # inserts content: never faithful


def test_11_bisect_drops_the_failing_pass() -> None:
    b = mk(1, 1, "Check the\nbelt  and the pulley.")
    passes = [*plan_passes(P, False)]
    passes.insert(3, Pass("broken", _bad))
    r = run(b, passes=passes).entry
    assert r.passes_rejected == ["broken"]
    assert r.fallback and r.faith_passed
    assert r.clean_text == "Check the belt and the pulley."
    assert r.rejected[0].stage == "deterministic"
    assert fallback_detail(r) == "deterministic: faithfulness; pass: broken"


def test_11_all_passes_broken_is_raw() -> None:
    raw = "Check the\nbelt."
    b = mk(1, 1, raw)
    r = run(b, passes=[Pass("broken1", _bad), Pass("broken2", _bad)]).entry
    assert r.stage == "raw" and r.clean_text == raw and r.passes == []
    assert r.passes_rejected == ["broken1", "broken2"] and r.fallback and r.faith_passed


def test_11_monkeypatched_pass_inserting_a_char(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_join(text: str, ctx: PassCtx) -> str:
        return text.replace("\n", " ") + "!"

    monkeypatch.setattr(rules, "P_JOIN", Pass("join_lines", bad_join))
    monkeypatch.setattr(
        rules,
        "PASSES",
        tuple(rules.P_JOIN if p.name == "join_lines" else p for p in rules.PASSES),
    )
    b = mk(1, 1, "lubri-\ncation  points")
    r = run(b).entry
    assert r.passes_rejected == ["join_lines"]
    assert r.clean_text == "lubrication points" and r.fallback


# -- 12 residual triggers -------------------------------------------------------------------


def _residual(b: Block, layout_risk: bool = False, lexicon: Lexicon | None = None) -> list[str]:
    pctx = PassCtx(block_type=b.type, lexicon=lexicon or Lexicon())
    d = compose(b.raw_text, plan_passes(b.type, False), pctx)
    return list(residual_reasons(b, d, layout_risk))


def test_12_residual_reasons() -> None:
    assert _residual(mk(1, 1, "Do not re-\nenter the tank.")) == ["ambiguous_hyphen"]
    assert _residual(mk(1, 1, "Do not adjust-\nment the tank.")) == []
    other = BlockType.other
    assert _residual(mk(1, 1, "Torque the bolt\nto the limit.", other)) == ["mid_sentence_break"]
    assert _residual(mk(1, 1, "Torque the bolt.\nThen check.", other)) == []
    assert _residual(mk(1, 1, "• Torque the bolt\n• then check", BlockType.list)) == []
    swapped = mk(1, 1, "B comes second.\nA comes first.", texts={
        "pymupdf": "B comes second.\nA comes first.",
        "docling": "A comes first.\nB comes second.",
    })  # fmt: skip
    assert _residual(swapped, layout_risk=True) == ["reading_order"]
    assert _residual(swapped, layout_risk=False) == []
    same = mk(1, 1, "A comes first.\nB comes second.")
    assert _residual(same, layout_risk=True) == []
    for t in (BlockType.heading, BlockType.caption, BlockType.table):
        assert _residual(mk(1, 1, "re-\nenter it\nnow", t)) == []


def test_12_mode_off_and_residual_call_counts() -> None:
    sink = ListSink()
    prov = MockProvider(sink=sink)
    blocks = [mk(1, 1, "Do not re-\nenter."), mk(1, 2, "Check the\nbelt.")]
    doc = doc_of(blocks)
    sel = {b.id for b in blocks}
    entries, _ = clean_document(doc, blocks, [], sel, mode="off", provider=prov)
    assert len(sink) == 0 and all(e.llm is None for e in entries)
    entries, _ = clean_document(doc, blocks, [], sel, mode="residual", provider=prov)
    assert len(sink) == sum(1 for e in entries if e.residual) == 1
    entries, _ = clean_document(doc, blocks, [], sel, mode="always", provider=prov)
    assert len(sink) == 3


RESIDUAL_CASES = {
    # reason: (block, its context, a reply the chain accepts, a reply it rejects + reason)
    "ambiguous_hyphen": (
        mk(1, 1, "Do not re-\nenter the tank."),
        bctx(),
        "Do not re-enter the tank.",
        ("Do not re-enter the tanks.", "chars"),
    ),
    "mid_sentence_break": (
        mk(1, 2, "Torque the bolt\nto the limit.", BlockType.other),
        bctx(),
        "Torque the bolt to the limit.",
        ("Torque the bolt to the 35 limit.", "chars"),
    ),
    "reading_order": (
        mk(1, 3, "B comes second.\nA comes first.", texts={
            "pymupdf": "B comes second.\nA comes first.",
            "docling": "A comes first.\nB comes second.",
        }),
        bctx(n_columns=2),
        "A comes first. B comes second.",
        ("A comes first.", "chars"),
    ),
}  # fmt: skip


def _const(reply: str) -> Any:
    return lambda _messages: reply


@pytest.mark.parametrize("reason", sorted(RESIDUAL_CASES))
def test_12_each_residual_reason_calls_the_llm_once(reason: str) -> None:
    """Synthetic blocks for each residual reason (the fixtures have none): residual mode calls
    the LLM exactly once, and its output goes through V1-V5 + the faithfulness check."""
    b, c, good, (bad, why) = RESIDUAL_CASES[reason]
    for reply, accepted in ((good, True), (bad, False)):
        sink = ListSink()
        prov = MockProvider(sink=sink, responses={Task.cleanup: _const(reply)})
        res = run(b, ctx=c, provider=prov, mode="residual")
        e = res.entry
        assert e.residual == [reason]
        assert res.llm_called and len(sink) == 1
        assert e.llm is not None
        if accepted:
            assert e.llm.outcome == "accepted" and e.stage == "llm" and e.clean_text == good
            assert e.faith_passed and not e.fallback
        else:
            assert e.llm.outcome == "rejected" and e.llm.reason == why
            assert e.stage != "llm" and e.clean_text != bad and e.fallback
            assert [r.stage for r in e.rejected] == ["llm"]
        # mode off: never called
        sink_off = ListSink()
        off = run(b, ctx=c, provider=MockProvider(sink=sink_off), mode="off")
        assert not off.llm_called and len(sink_off) == 0 and off.entry.residual == [reason]


def test_12_residual_call_count_equals_residual_blocks() -> None:
    blocks = [case[0] for case in RESIDUAL_CASES.values()] + [mk(1, 4, "Check the\nbelt.")]
    sink = ListSink()
    prov = MockProvider(sink=sink)
    layouts: list[Any] = []
    doc = doc_of(blocks)
    entries, _ = clean_document(
        doc, blocks, layouts, {b.id for b in blocks}, mode="residual", provider=prov
    )
    with_residual = [e for e in entries if e.residual]
    assert len(with_residual) >= 2  # ambiguous_hyphen and mid_sentence_break (no layout here)
    assert len(sink) == len(with_residual)
    assert all((e.llm is not None) == bool(e.residual) for e in entries)


# -- 13 prompt ------------------------------------------------------------------------------


class Spy(MockProvider):
    seen: list[tuple[list[Message], float]]

    def _chat_raw(
        self,
        task: Task,
        messages: Sequence[Message],
        json_schema: Mapping[str, Any] | None,
        temperature: float,
    ) -> RawChat:
        self.seen.append((list(messages), temperature))
        return super()._chat_raw(task, messages, json_schema, temperature)


def test_13_prompt_and_echo(tmp_path: Path) -> None:
    sink = ListSink()
    prov = Spy(sink=sink, cache=LLMCache(tmp_path / "cache"))
    prov.seen = []
    raw = "Do not re-\nenter the\ntank."
    b = mk(1, 1, raw)
    r = run(b, provider=prov).entry
    msgs, temp = prov.seen[0]
    assert msgs[0].role == "system" and msgs[0].content.startswith("clean-v1")
    assert msgs[0].content == SYSTEM_PROMPT
    assert msgs[-1].content == "<raw>Do not re-\nenter the tank.</raw>"  # break restored
    assert temp == 0.0
    assert r.llm is not None and r.llm.outcome == "accepted"
    assert r.clean_text == "Do not reenter the tank." and r.stage == "deterministic"
    assert not r.fallback
    again = run(b, provider=prov)
    assert again.llm_called and again.llm_cached and len(prov.seen) == 1
    assert [x.cached for x in sink] == [False, True]


# -- 14 output validation -------------------------------------------------------------------


def _check_for(b: Block, ctx: BlockContext | None = None) -> Any:
    kw = faith_kwargs(b, ctx or bctx())

    def check(c: str) -> FaithOutcome:
        return check_faithfulness_ex(b.raw_text, c, **kw)

    return check


@pytest.mark.parametrize(
    ("out", "reason"),
    [
        ("", "empty"),
        ("  \n ", "empty"),
        ("<raw>Torque the M8 bolt to 35 N·m.</raw>", "tags"),
        ("Here is the text: Torque the M8 bolt to 35 N·m.", "chars"),
        ("```\nTorque the M8 bolt to 35 N·m.\n```", "chars"),
        ("Torque the M8 bolt to 36 N·m.", "chars"),
        ("Torque the M8 bolt to 351 N·m.", "chars"),
        ("Torque the bolt to 35 N·m.", "chars"),
        ("Torque the M8 bolt to 35 N·m. Done.", "chars"),
        ("Torque the M8 bolt to 35 N·m", "chars"),
    ],
)
def test_14_validation_table(out: str, reason: str) -> None:
    x = "Torque the M8 bolt to 35 N·m."
    b = mk(1, 1, x)
    v = validate_output(x, out, P, _check_for(b))
    assert v.reason == reason


def test_14_sign_and_numeric_tokens() -> None:
    x = "Gap ±0.05 mm."
    b = mk(1, 1, x)
    assert validate_output(x, "Gap +0.05 mm.", P, _check_for(b)).reason == "chars"
    # a number split into two tokens keeps every char: only V3 sees it
    y = "Use 10.5 mm."
    v = validate_output(y, "Use 10. 5 mm.", P, _check_for(mk(1, 1, y)))
    assert v.reason == "numeric_tokens"


def test_14_reorder_needs_another_reader() -> None:
    raw = "Second step is next.\nFirst step is here."
    swapped = "First step is here. Second step is next."
    lone = mk(1, 1, raw)
    v = validate_output(raw, swapped, P, _check_for(lone, bctx(n_columns=2)))
    assert v.reason == "faithfulness"
    assert any(x.kind.value == "reorder" for x in v.violations)
    attested = mk(
        1, 1, raw, texts={"pymupdf": raw, "docling": "First step is here.\nSecond step is next."}
    )
    ctx = bctx(n_columns=2)
    v = validate_output(raw, swapped, P, _check_for(attested, ctx))
    assert v.reason is None and v.outcome is not None and v.outcome.reordered
    s = score_block(attested.model_copy(update={"clean_text": swapped}), ctx, threshold=0.85)
    faith = {x.name.value: x for x in s.signals}["faithfulness"]
    assert faith.value == 0.9


def test_14_llm_reorder_end_to_end() -> None:
    raw = "Second step is next.\nFirst step is here."
    b = mk(
        1, 1, raw, texts={"pymupdf": raw, "docling": "First step is here.\nSecond step is next."}
    )
    prov = MockProvider(
        sink=ListSink(), responses={Task.cleanup: "First step is here. Second step is next."}
    )
    r = run(b, ctx=bctx(n_columns=2), provider=prov, mode="always").entry
    assert r.llm is not None and r.llm.outcome == "accepted" and r.stage == "llm"
    assert r.clean_text == "First step is here. Second step is next."


# -- 15 provider error ----------------------------------------------------------------------


class Down(MockProvider):
    def _chat_raw(self, *a: Any, **k: Any) -> RawChat:
        raise ProviderError("connection refused")


def test_15_provider_error_keeps_deterministic() -> None:
    b = mk(1, 1, "Do not re-\nenter the\ntank.")
    r = run(b, provider=Down(sink=ListSink())).entry
    assert (
        r.llm is not None
        and r.llm.outcome == "error"
        and "connection refused" in (r.llm.reason or "")
    )
    assert r.clean_text == "Do not reenter the tank." and r.rejected == [] and not r.fallback


def test_rejected_llm_output_is_a_fallback() -> None:
    b = mk(1, 1, "Do not re-\nenter the\ntank.")
    prov = MockProvider(sink=ListSink(), responses={Task.cleanup: "Do not enter the tank."})
    r = run(b, provider=prov).entry
    assert r.llm is not None and r.llm.outcome == "rejected" and r.llm.reason == "chars"
    assert r.rejected[0].stage == "llm" and r.rejected[0].text == "Do not enter the tank."
    assert r.fallback and r.clean_text == "Do not reenter the tank."
    s = score_block(
        b.model_copy(update={"clean_text": r.clean_text}),
        bctx(),
        threshold=0.85,
        fallback=fallback_detail(r),
    )
    faith = {x.name.value: x for x in s.signals}["faithfulness"]
    assert faith.value == 0.5 and faith.critical and s.status == "queued"
    assert faith.detail == "cleanup candidate rejected (llm: chars); kept deterministic result"


def test_det_result_is_frozen() -> None:
    d = DetResult("x", [], [])
    with pytest.raises(AttributeError):
        d.text = "y"  # type: ignore[misc]


# -- V2 bullet allowance = the deterministic P3 rule; signs are never bullets ----------------

L = BlockType.list


@pytest.mark.parametrize(
    ("x", "out", "type", "ok"),
    [
        # prose: only the unambiguous glyphs •◦▪‣● may become •; – - * + stay
        ("Range:\n– 40 °C min", "Range:\n• 40 °C min", P, False),
        ("Note:\n* keep it dry", "Note:\n• keep it dry", P, False),
        ("Steps:\n- open the cover", "Steps:\n• open the cover", P, False),
        ("Steps:\n+ open the cover", "Steps:\n• open the cover", P, False),
        ("Steps:\n◦ open the cover", "Steps:\n• open the cover", P, True),
        # lists: the list glyph set, but a sign before a digit is not a bullet
        ("- open the cover\n¢ remove the belt", "• open the cover\n• remove the belt", L, True),
        ("• supply\n+ 5 V rail", "• supply\n• 5 V rail", L, False),
        ("• range\n– 40 °C", "• range\n• 40 °C", L, False),
        ("• range\n- 12 V", "• range\n• 12 V", L, False),
        # a glyph that is not at a line start is never a bullet
        ("Use the wrench * twice.", "Use the wrench • twice.", P, False),
    ],
)
def test_v2_bullets_match_the_deterministic_rule(
    x: str, out: str, type: BlockType, ok: bool
) -> None:
    b = mk(1, 1, x, type)
    v = validate_output(x, out, type, _check_for(b))
    assert (v.reason is None) == ok, v
    if not ok:
        assert v.reason == "chars"


def test_v2_bullets_with_v4_alone() -> None:
    """The sign rule is part of AE4 itself: V4 rejects a sign turned into a bullet."""
    for x, out, type in (
        ("• supply\n+ 5 V rail", "• supply\n• 5 V rail", L),
        ("Range:\n– 40 °C min", "Range:\n• 40 °C min", P),
        ("• range\n- 12 V", "• range\n• 12 V", L),
    ):
        v = validate_output(x, out, type, _check_for(mk(1, 1, x, type)), prefilter=False)
        assert v.reason == "faithfulness", (x, v)


def test_p3_never_turns_a_sign_into_a_bullet() -> None:
    lst = PassCtx(block_type=L)
    for keep in ("+ 5 V supply", "- 12 V line", "– 40 °C", "-12 V", "+5 V", "-  3.5 mm"):
        assert rules.bullets(keep, lst) == keep
    assert rules.bullets("+ remove it\n- 5 V\n- check", lst) == "• remove it\n- 5 V\n• check"
    raw = "+ 5 V supply\n- 12 V line"
    out = compose(raw, plan_passes(L, False), lst).text
    assert out == raw
    v = validate_output(raw, out, L, _check_for(mk(1, 1, raw, L)))
    assert v.reason is None


# -- V5 whitespace inside a token with a digit or "/" -----------------------------------------


@pytest.mark.parametrize(
    ("x", "out"),
    [
        ("Replace seal P/N 4471-A if worn.", "Replace seal P/N 4471- A if worn."),
        ("Replace seal P/N 4471-A if worn.", "Replace seal P/N 4471 -A if worn."),
        ("Use a 3/4 in. wrench.", "Use a 3 / 4 in. wrench."),
        ("Use a 3/4 in. wrench.", "Use a 3/ 4 in. wrench."),
        ("Check P/N 4471 -A first.", "Check P/N 4471-A first."),
        ("Torque M8 bolts and P/ N parts.", "Torque M8 bolts and P/N parts."),
    ],
)
def test_v5_whitespace_inside_numeric_tokens_rejected(x: str, out: str) -> None:
    b = mk(1, 1, x)
    for prefilter in (True, False):
        v = validate_output(x, out, P, _check_for(b), prefilter=prefilter)
        assert v.reason in ("token_whitespace", "numeric_tokens"), (prefilter, v)
    assert validate_output(x, out, P, _check_for(b)).reason == "token_whitespace"


def test_v5_line_joins_around_numeric_tokens_pass() -> None:
    x = "Replace seal P/N 4471-A\nif worn; use a 3/4\nin. wrench."
    out = "Replace seal P/N 4471-A if worn; use a 3/4 in. wrench."
    assert validate_output(x, out, P, _check_for(mk(1, 1, x))).reason is None
