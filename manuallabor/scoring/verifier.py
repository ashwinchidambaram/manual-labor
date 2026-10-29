"""Optional llm_verifier: a separate model as a second reader (SPEC 5.1, design 2.10).

The verifier is never asked about its own output (skipped when it is the cleanup model) and
never asked to rate anything; its answer is validated strictly before it becomes a signal."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from manuallabor.contracts.block import Signal
from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import SignalName, Task
from manuallabor.contracts.llm import Message
from manuallabor.parse.text import collapse_ws
from manuallabor.providers.base import RAW_CLOSE, RAW_OPEN, ProviderError, ProviderSet
from manuallabor.scoring.types import VERIFIER_FLAG_VALUE, VERIFIER_MAX_SPAN, truncate

VERIFIER_SYSTEM: Final = (
    "You compare two versions of a passage from a technical manual: the raw extraction and "
    "a cleaned version. Report only differences in facts, numbers, units, part numbers or "
    "steps. Reply with the exact differing span copied from the text, or the single word NONE."
)
QUESTION: Final = (
    "Does the cleaned text change any fact, number, or step? Answer with the differing span or NONE"
)
_NONE_RE: Final = re.compile(r"(?i)none\.?")

Outcome = Literal[
    "ok",
    "flag",
    "skip_no_clean",
    "skip_unchanged",
    "skip_faith_failed",
    "skip_no_verifier",
    "skip_same_model",
    "verifier_invalid",
    "verifier_errors",
]


def same_model(a: ModelRef, b: ModelRef) -> bool:
    return (a.provider, a.model, a.api_base) == (b.provider, b.model, b.api_base)


def verifier_messages(raw: str, clean: str) -> list[Message]:
    return [
        Message(role="system", content=VERIFIER_SYSTEM),
        Message(
            role="user",
            content=f"{RAW_OPEN}{raw}{RAW_CLOSE}\n<clean>{clean}</clean>\n{QUESTION}",
        ),
    ]


def _unwrap(text: str) -> str:
    out = text.strip()
    for q in ('"', "'", "`"):
        if len(out) >= 2 and out[0] == q and out[-1] == q:
            return out[1:-1].strip()
    return out


def validate_answer(text: str, raw: str, clean: str) -> tuple[Outcome, Signal | None]:
    """Strict: NONE -> 1.0; a short verbatim span of raw or clean -> 0.2; anything else is
    discarded (the model's free text is never used as evidence)."""
    out = _unwrap(text)
    if _NONE_RE.fullmatch(out):
        return "ok", Signal(
            name=SignalName.llm_verifier, value=1.0, critical=False, detail="verifier: NONE"
        )
    if (
        1 <= len(out) <= VERIFIER_MAX_SPAN
        and re.search(r"\n[ \t]*\n", out) is None
        and (collapse_ws(out) in collapse_ws(clean) or collapse_ws(out) in collapse_ws(raw))
        and collapse_ws(out)
    ):
        return "flag", Signal(
            name=SignalName.llm_verifier,
            value=VERIFIER_FLAG_VALUE,
            critical=False,
            detail=truncate(f"verifier: {collapse_ws(out)!r}"),
        )
    return "verifier_invalid", None


@dataclass(frozen=True)
class VerifierPlan:
    """Whether the verifier may run for this project, and the provider set getter."""

    ref: ModelRef | None
    reason: Outcome | None  # skip reason for every block when ref is None
    providers: Callable[[], ProviderSet] | None


def plan_verifier(
    config: ProjectConfig, providers: Callable[[], ProviderSet] | None
) -> VerifierPlan:
    ref = config.model_for(Task.verifier)
    if ref is None:
        return VerifierPlan(None, "skip_no_verifier", None)
    cleanup = config.model_for(Task.cleanup)
    if cleanup is not None and same_model(ref, cleanup):
        return VerifierPlan(None, "skip_same_model", None)
    return VerifierPlan(ref, None, providers)


def llm_verifier(
    raw: str,
    clean: str | None,
    *,
    faith_passed: bool,
    plan: VerifierPlan,
) -> tuple[Outcome, Signal | None]:
    if clean is None:
        return "skip_no_clean", None
    if clean == raw:
        return "skip_unchanged", None
    if not faith_passed:
        return "skip_faith_failed", None
    if plan.ref is None or plan.providers is None:
        return plan.reason or "skip_no_verifier", None
    try:
        res = plan.providers().get(Task.verifier).chat(Task.verifier, verifier_messages(raw, clean))
    except ProviderError:
        return "verifier_errors", None
    return validate_answer(res.text, raw, clean)
