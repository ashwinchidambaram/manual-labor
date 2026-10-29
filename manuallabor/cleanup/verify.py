"""The candidate chain of one block (design 2.2): deterministic passes, bisect on failure, the
optional LLM pass, fallback. Every candidate goes through the exact faithfulness call that
scoring makes (``scoring.pipeline.faith_kwargs``), so both verdicts agree by construction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from manuallabor.cleanup.llm import build_messages, validate_output
from manuallabor.cleanup.residual import residual_reasons
from manuallabor.cleanup.rules import (
    AMBIGUOUS_MARK,
    DetResult,
    Pass,
    PassCtx,
    apply_pass,
    compose,
    restore_marks,
)
from manuallabor.cleanup.types import (
    LLM_TYPES,
    MAX_STORED_VIOLATIONS,
    REJECTED_TEXT_MAX,
    CleanEntry,
    FewShotExample,
    LlmMode,
    LlmOutcome,
    RejectedCandidate,
    Stage,
    raw_sha256,
)
from manuallabor.contracts.block import (
    Block,
    FaithfulnessResult,
    FaithfulnessViolation,
    NumericVariant,
)
from manuallabor.contracts.enums import Task
from manuallabor.providers.base import Provider, ProviderError
from manuallabor.scoring.faithfulness import FaithOutcome, check_faithfulness_ex
from manuallabor.scoring.pipeline import faith_kwargs
from manuallabor.scoring.types import BlockContext

ERROR_MAX = 300


def verify(
    block: Block, ctx: BlockContext, candidate: str, variants: Sequence[NumericVariant] = ()
) -> FaithfulnessResult:
    """The full-context faithfulness verdict of ``candidate`` as this block's clean text."""
    return check_faithfulness_ex(
        block.raw_text, candidate, **faith_kwargs(block, ctx, variants)
    ).result


def _rejected(
    stage: str,
    reason: str,
    text: str,
    violations: Sequence[FaithfulnessViolation] = (),
    detail: str | None = None,
) -> RejectedCandidate:
    return RejectedCandidate.model_validate(
        {
            "stage": stage,
            "reason": reason,
            "detail": detail,
            "text": text[:REJECTED_TEXT_MAX],
            "violations": [v.model_dump(mode="json") for v in violations[:MAX_STORED_VIOLATIONS]],
        }
    )


@dataclass(frozen=True)
class BlockClean:
    entry: CleanEntry
    llm_called: bool = False
    llm_cached: bool = False


def clean_block(
    block: Block,
    ctx: BlockContext,
    *,
    input_hash: str,
    passes: Sequence[Pass],
    pctx: PassCtx,
    variants: Sequence[NumericVariant] = (),
    mode: LlmMode = "residual",
    provider: Provider | None = None,
    examples: Sequence[FewShotExample] = (),
    prefilter: bool = True,
) -> BlockClean:
    kw = faith_kwargs(block, ctx, variants)
    raw = block.raw_text

    def check(candidate: str) -> FaithOutcome:
        return check_faithfulness_ex(raw, candidate, **kw)

    rejected: list[RejectedCandidate] = []
    passes_rejected: list[str] = []
    full = compose(raw, passes, pctx)
    out = check(full.text)
    used: list[Pass] = list(passes)
    det: DetResult = full
    if not out.result.passed:
        # bisect: each pass in order on top of the accepted ones; a failing pass is dropped
        rejected.append(
            _rejected("deterministic", "faithfulness", full.text, out.result.violations)
        )
        x, applied, dh = raw, [], []
        used = []
        for p in passes:
            y, d = apply_pass(p, x, pctx)
            if y == x:
                used.append(p)
                continue
            if check(y).result.passed:
                x = y
                applied.append(p.name)
                dh.extend(d)
                used.append(p)
            else:
                passes_rejected.append(p.name)
        det = DetResult(x, applied, dh)
        out = check(x)

    residual = residual_reasons(block, det, ctx.layout_risk)
    final, final_out = det.text, out
    stage: Stage = "deterministic" if det.applied else "raw"
    llm: LlmOutcome | None = None
    called = cached = False
    if (
        provider is not None
        and block.type in LLM_TYPES
        and (mode == "always" or (mode == "residual" and residual))
    ):
        x = det.text
        if "ambiguous_hyphen" in residual and AMBIGUOUS_MARK not in raw:
            # the model sees the break it is asked to decide (3.2)
            x = restore_marks(compose(raw, used, replace(pctx, mark_ambiguous=True)).text)
        called = True
        try:
            res = provider.chat(Task.cleanup, build_messages(x, examples))
        except ProviderError as exc:
            llm = LlmOutcome(outcome="error", reason=str(exc)[:ERROR_MAX])
        else:
            cached = res.log.cached
            v = validate_output(x, res.text, block.type, check, prefilter=prefilter)
            if v.reason is None:
                llm = LlmOutcome(outcome="accepted")
                assert v.candidate is not None and v.outcome is not None
                # an unchanged reply (echo) keeps the deterministic result
                if v.candidate not in (x, det.text):
                    final, final_out, stage = v.candidate, v.outcome, "llm"
            else:
                llm = LlmOutcome(outcome="rejected", reason=v.reason)
                rejected.append(_rejected("llm", v.reason, res.text, v.violations, v.detail))

    learned = [n.split(":", 1)[1] for n in det.applied if n.startswith("learned:")]
    entry = CleanEntry(
        block_id=block.id,
        input_hash=input_hash,
        raw_sha256=raw_sha256(raw),
        clean_text=final,
        stage=stage,
        passes=list(det.applied),
        dh=list(det.dh),
        passes_rejected=passes_rejected,
        residual=residual,
        llm=llm,
        rejected=rejected,
        fallback=bool(passes_rejected or rejected),
        faith_passed=final_out.result.passed,
        alignment_ratio=final_out.result.alignment_ratio,
        learned_rules=learned,
        few_shot=[e.id for e in examples] if called else [],
    )
    return BlockClean(entry, called, cached)
