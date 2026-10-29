"""Rounds and history of one flag (design 10 section 3.1). Pure."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from manuallabor.contracts.enums import ProposalKind, ProposalStatus
from manuallabor.contracts.proposal import PriorAttempt, Proposal

__all__ = ["failed_checks", "next_round", "priors_for", "summarize"]

SETTLED = (ProposalStatus.rejected, ProposalStatus.superseded)


def summarize(p: Proposal) -> str:
    """A one-line (text kinds: full text) description of what a proposal changed."""
    if p.kind in (ProposalKind.text, ProposalKind.cells):
        return p.proposal_text or ""
    if p.kind == ProposalKind.bbox and p.proposed_bbox is not None:
        x0, y0, x1, y1 = (round(v, 1) for v in p.proposed_bbox)
        return f"bbox [{x0}, {y0}, {x1}, {y1}]"
    if p.kind == ProposalKind.attach and p.proposed_attach is not None:
        return f"attach {p.proposed_attach.figure_id} → {p.proposed_attach.article_id}"
    if p.kind == ProposalKind.regroup and p.proposed_regroup is not None:
        return f"move {p.proposed_regroup.block_id} → {p.proposed_regroup.to_topic_slug}"
    return ""


def failed_checks(p: Proposal) -> list[str]:
    return [r.check for r in p.rechecks if not r.passed]


def priors_for(
    proposals: Iterable[Proposal],
    reason_of: Callable[[Proposal], tuple[str | None, datetime]],
) -> list[PriorAttempt]:
    """The settled (rejected or superseded) attempts of one flag, by id, as `PriorAttempt`.
    `reason_of(p)` gives the reviewer's reason and the time of the decision. The model's own
    rationale rides along for display; it is never fed back to a model."""
    out: list[PriorAttempt] = []
    for p in sorted(proposals, key=lambda x: x.id):
        if p.status not in SETTLED:
            continue
        reason, at = reason_of(p)
        out.append(
            PriorAttempt(
                proposal_id=p.id,
                proposal_text=summarize(p),
                rationale=p.rationale,
                status=p.status,
                decided_at=at,
                kind=p.kind,
                reason=reason,
                failed_checks=failed_checks(p),
            )
        )
    return out


def next_round(priors: list[PriorAttempt]) -> int:
    return len(priors) + 1
