"""The agent service of the serve process (design 10 sections 3.8, 3.9).

It never calls a model: proposals are produced by a job (worker or `labor agent`) and arrive
as events. Accepting re-uses the rechecks stored with the proposal, guarded by the basis hash:
if anything a check depended on changed, the proposal is superseded instead of applied."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import Field

from manuallabor.agent.data import target_slug
from manuallabor.agent.errors import AgentConflict
from manuallabor.agent.inputs import basis_sha256, eligible_items
from manuallabor.agent.projections import project_outcomes_file
from manuallabor.agent.recheck import numbers_changed
from manuallabor.agent.types import AgentPlan, Skip
from manuallabor.contracts._base import ContractModel, TargetId
from manuallabor.contracts.enums import (
    BlockType,
    FlagStatus,
    ProposalKind,
    ProposalStatus,
)
from manuallabor.contracts.flag import Flag
from manuallabor.contracts.proposal import Proposal
from manuallabor.project import ProjectPaths
from manuallabor.state import projections
from manuallabor.state.data import ProjectData
from manuallabor.state.errors import InvalidOp, NotFound
from manuallabor.state.models import ActionKind, JobInfo, RegroupIn, RunPlanIn
from manuallabor.state.review import ReviewService, display_text, load_review_blocks
from manuallabor.state.store import Store

__all__ = ["AgentItemView", "AgentService"]

# outcomes a pass records after working on an item (the others are skips decided before it)
_RAN = frozenset({"error", "no_proposal", "stale"})


class AgentItemView(ContractModel):
    flag: Flag
    target_id: TargetId
    round: int
    pending_proposal_id: str | None = None
    last_outcome: str | None = None
    last_detail: str | None = None
    # How many agent passes worked on this flag: the passes started for it (`agent_run`
    # actions), never fewer than its proposals, and at least one once a pass recorded an outcome.
    # `round` alone cannot say it: a pass that ends in an error leaves no proposal.
    attempts: int = Field(default=0, ge=0)


class _Runner(Protocol):
    def enqueue(self, plan: RunPlanIn, kind: str = "run", files: Sequence[Any] = ()) -> JobInfo: ...
    def enqueue_raw(self, plan: dict[str, Any], kind: str) -> JobInfo: ...
    def get(self, job_id: str) -> JobInfo: ...


class AgentService:
    def __init__(
        self,
        paths: ProjectPaths,
        store: Store,
        data: ProjectData,
        review: ReviewService,
        figures: Any,
        scope: Any,
        runner: _Runner,
    ) -> None:
        self.paths = paths
        self.store = store
        self.data = data
        self.review = review
        self.figures = figures
        self.scope = scope
        self.runner = runner
        self._lock = threading.RLock()

    # -- outcomes file ------------------------------------------------------------------------

    def _outcomes(self, change: dict[str, dict[str, Any] | None]) -> None:
        with self._lock:
            project_outcomes_file(self.paths, change)

    def _record_skips(self, skips: Sequence[Skip]) -> None:
        change: dict[str, dict[str, Any] | None] = {}
        for s in skips:
            if s.outcome == "pending":
                continue
            change[s.flag_id] = {"outcome": s.outcome, "detail": s.detail, "round": None}
        if change:
            self._outcomes(change)

    # -- reads --------------------------------------------------------------------------------

    def proposals(
        self,
        status: ProposalStatus | None = None,
        flag_id: str | None = None,
        doc: str | None = None,
    ) -> list[Proposal]:
        return self.store.proposals(status=status, flag_id=flag_id, doc=doc)

    def proposal(self, proposal_id: str) -> Proposal:
        p = self.store.get_proposal(proposal_id)
        if p is None:
            raise NotFound(proposal_id)
        return p

    def items(self) -> list[AgentItemView]:
        cfg = self.paths.load_config()
        items, skips = eligible_items(self.paths, self.store, self.data, cfg, include_pending=True)
        last = project_outcomes_file(self.paths, {})
        pending = {p.flag_id: p.id for p in self.store.proposals(status=ProposalStatus.pending)}
        flags = {f.id: f for f in self.store.flags(FlagStatus.open)}
        passes = self._passes()

        def attempts(flag_id: str, round_: int, outcome: str | None) -> int:
            ran = outcome in _RAN  # a skip is decided before a pass and is not an attempt
            return max(passes.get(flag_id, 0), round_ - 1, 1 if ran else 0)

        out: list[AgentItemView] = []
        for it in items:
            flag = flags.get(it.flag_id)
            if flag is None:
                # resolved between the two reads (eligible_items read the open flags first):
                # no longer open, so not an item (Playwright run 2026-10-30, a KeyError 500)
                continue
            o = last.get(it.flag_id) or {}
            out.append(
                AgentItemView(
                    flag=flag,
                    target_id=it.target_id,
                    round=it.round,
                    pending_proposal_id=pending.get(it.flag_id),
                    last_outcome=o.get("outcome"),
                    last_detail=o.get("detail"),
                    attempts=attempts(it.flag_id, it.round, o.get("outcome")),
                )
            )
        for s in skips:
            f = flags.get(s.flag_id)
            if f is None:
                continue
            rnd = len(self.store.proposals(flag_id=f.id)) + 1
            out.append(
                AgentItemView(
                    flag=f,
                    target_id=s.target_id,
                    round=rnd,
                    pending_proposal_id=pending.get(f.id),
                    last_outcome=s.outcome,
                    last_detail=s.detail,
                    attempts=attempts(f.id, rnd, None),
                )
            )
        return sorted(out, key=lambda v: v.flag.id)

    def _passes(self) -> dict[str, int]:
        """flag id -> the number of agent passes started with it in their plan."""
        n: dict[str, int] = {}
        for a in self.store.actions_of((ActionKind.agent_run,)):
            for fid in a.payload.get("flags") or ():
                n[str(fid)] = n.get(str(fid), 0) + 1
        return n

    # -- the run ------------------------------------------------------------------------------

    def plan(
        self, docs: Sequence[str] | None, flag_ids: Sequence[str] | None
    ) -> tuple[AgentPlan, list[Skip]]:
        cfg = self.paths.load_config()
        items, skips = eligible_items(
            self.paths, self.store, self.data, cfg, docs=docs, flag_ids=flag_ids
        )
        self._record_skips(skips)
        return AgentPlan(items=items), skips

    def enqueue(
        self, docs: Sequence[str] | None, flag_ids: Sequence[str] | None, request_id: str
    ) -> JobInfo:
        prev = self.store.action_by_request(request_id)
        if prev is not None:
            return self.runner.get(str(prev.payload["job_id"]))
        plan, skips = self.plan(docs, flag_ids)
        if not plan.items:
            raise AgentConflict("no_open_flags", self.no_items_detail(skips))
        with self.store.tx():
            job = self.runner.enqueue_raw(plan.model_dump(mode="json"), "agent")
            self.store.append_action(
                ActionKind.agent_run,
                "agent",
                payload={
                    "job_id": job.id,
                    "flags": [i.flag_id for i in plan.items],
                    "skipped": [[s.flag_id, s.outcome] for s in skips],
                    "_outcome": job.id,
                },
                request_id=request_id,
            )
        return job

    @staticmethod
    def no_items_detail(skips: Sequence[Skip]) -> str:
        if not skips:
            return "no open flags to work on"
        parts = [
            f"{s.flag_id}: {s.outcome}" + (f" ({s.detail})" if s.detail else "") for s in skips
        ]
        return "no open flag can be processed; " + "; ".join(parts[:10])

    # -- ingestion (supervisor thread or CLI) ---------------------------------------------------

    def ingest_event(self, job_id: str | None, o: dict[str, Any]) -> None:
        ev = o.get("event")
        if ev == "agent_outcome":
            f = self.store.get_flag(str(o["flag_id"]))
            if f is not None and f.status == FlagStatus.open:
                self._outcomes(
                    {
                        f.id: {
                            "outcome": o["outcome"],
                            "detail": o.get("detail"),
                            "round": o.get("round"),
                        }
                    }
                )
            return
        if ev != "proposal":
            return
        d = dict(o["draft"])
        flag = self.store.get_flag(str(d["flag_id"]))
        if flag is None or flag.status != FlagStatus.open:
            return
        if self.store.proposal_for(flag.id, int(d["round"])) is not None:
            return
        if self.store.proposals(status=ProposalStatus.pending, flag_id=flag.id):
            return
        plan_basis = o.get("plan_basis")
        if plan_basis is not None:
            kind = ProposalKind(d["kind"])
            slug = target_slug(d["target_id"])
            current = None
            if kind in (ProposalKind.text, ProposalKind.cells):
                current = self._display_text(slug, d["target_id"])
            now = basis_sha256(self.paths, self.data, d["target_id"], kind, current, None)
            if now != plan_basis:
                self._outcomes(
                    {
                        flag.id: {
                            "outcome": "stale",
                            "detail": "the project changed while the agent ran",
                            "round": d["round"],
                        }
                    }
                )
                return
        with self.store.tx():
            n = self.store.next_proposal_n()
            p = Proposal.model_validate(
                {
                    **d,
                    "id": f"prop-{n:06d}",
                    "status": "pending",
                    "created_at": self.store.now(),
                }
            )
            try:
                self.store.add_proposal(p)
            except sqlite3.IntegrityError:
                return
            self.store.after_commit(lambda: projections.project_proposals(self.store, self.paths))
        self._outcomes({flag.id: None})

    def _display_text(self, slug: str, block_id: str) -> str | None:
        for b in load_review_blocks(self.paths, self.store, slug):
            if b.id == block_id:
                return display_text(b)
        return None

    # -- decisions ----------------------------------------------------------------------------

    def _settle(
        self, p: Proposal, status: ProposalStatus, action_id: int | None, **upd: Any
    ) -> Proposal:
        """pending -> status as a compare-and-swap inside the caller's transaction: if another
        decision settled the proposal first, raise `already_decided` and the whole transaction
        (decision, override, flag resolution) rolls back."""
        new = p.model_copy(update={"status": status, **upd})
        if not self.store.set_proposal(new, action_id, expect=ProposalStatus.pending):
            raise AgentConflict("already_decided", f"{p.id} was decided by another request")
        self.store.after_commit(lambda: projections.project_proposals(self.store, self.paths))
        return new

    def _claim(self, proposal_id: str) -> Proposal:
        """The first statement of a decision transaction (BEGIN IMMEDIATE holds the write lock
        from here to COMMIT): re-read the proposal; anything but pending means a concurrent
        request decided it after this one's pre-checks."""
        cur = self.proposal(proposal_id)
        if cur.status != ProposalStatus.pending:
            raise AgentConflict("already_decided", f"{cur.id} is {cur.status.value}")
        return cur

    def _fresh(self, p: Proposal) -> bool:
        slug = target_slug(p.target_id)
        current = None
        if p.kind in (ProposalKind.text, ProposalKind.cells):
            current = self._display_text(slug, p.target_id)
        return basis_sha256(self.paths, self.data, p.target_id, p.kind, current, p.vision) == (
            p.basis_sha256
        )

    def _check_accept(self, p: Proposal) -> None:
        if p.status != ProposalStatus.pending:
            raise AgentConflict("not_pending", f"{p.id} is {p.status.value}")
        if not self._fresh(p):
            with self.store.tx():
                self._settle(self._claim(p.id), ProposalStatus.superseded, None)
            raise AgentConflict(
                "stale_proposal", f"{p.id}: the project changed since it was proposed"
            )
        missing = p.missing_checks()
        if missing:
            raise AgentConflict(
                "checks_failed",
                f"{p.id}: the check list is incomplete, missing: " + ", ".join(missing),
            )
        if not p.all_checks_passed:
            failed = ", ".join(r.check for r in p.rechecks if not r.passed)
            raise AgentConflict("checks_failed", f"{p.id} failed: {failed}")

    def _replayed(self, request_id: str, proposal_id: str) -> Proposal | None:
        prev = self.store.action_by_request(request_id)
        if prev is None:
            return None
        return self.proposal(proposal_id)

    def accept(self, proposal_id: str, request_id: str) -> Proposal:
        done = self._replayed(request_id, proposal_id)
        if done is not None:
            return done
        p = self.proposal(proposal_id)
        follow = self._accept(p, request_id, bulk=False)
        self._follow_up(follow)
        return self.proposal(proposal_id)

    def _accept(self, p: Proposal, request_id: str, *, bulk: bool) -> list[RunPlanIn]:
        self._check_accept(p)
        slug = target_slug(p.target_id)
        follow: list[RunPlanIn] = []
        with self.store.tx():
            p = self._claim(p.id)
            if p.kind in (ProposalKind.text, ProposalKind.cells):
                assert p.proposal_text is not None
                out = self.review.apply_agent_edit(
                    p.target_id, p.proposal_text, p, request_id, bulk=bulk
                )
                aid = out.action_id
            else:
                meta = {"proposal": p.model_dump(mode="json"), "proposal_id": p.id, "bulk": bulk}
                if p.kind == ProposalKind.attach:
                    assert p.proposed_attach is not None
                    pa = p.proposed_attach
                    self.figures.attach(
                        pa.figure_id,
                        pa.article_id,
                        pa.anchor_block_id,
                        request_id,
                        screen="agent",
                        meta=meta,
                    )
                    follow.append(RunPlanIn(to="score2", docs=[slug]))
                elif p.kind == ProposalKind.bbox:
                    assert p.proposed_bbox is not None
                    self.figures.set_bbox(
                        p.target_id,
                        list(p.proposed_bbox),
                        request_id,
                        screen="agent",
                        meta=meta,
                    )
                    follow.append(RunPlanIn(to="score2", docs=[slug], force=["figures"]))
                else:
                    assert p.proposed_regroup is not None
                    pr = p.proposed_regroup
                    self.scope.regroup(
                        RegroupIn(
                            doc_id=slug,
                            kind="move",
                            block_id=pr.block_id,
                            to_topic_slug=pr.to_topic_slug,
                            request_id=request_id,
                        ),
                        screen="agent",
                        meta=meta,
                    )
                    follow.append(RunPlanIn(to="group", docs=[slug]))
                act = self.store.action_by_request(request_id)
                assert act is not None
                aid = act.id
                self.store.resolve_flag(p.flag_id, f"proposal {p.id} accepted", aid)
            self._settle(p, ProposalStatus.accepted, aid)
        return follow

    def _follow_up(self, plans: Sequence[RunPlanIn]) -> None:
        seen: set[str] = set()
        for plan in plans:
            key = plan.model_dump_json()
            if key not in seen:
                seen.add(key)
                self.runner.enqueue(plan)

    def edit(
        self,
        proposal_id: str,
        *,
        text: str | None,
        bbox: list[float] | None,
        confirm_content_change: bool,
        request_id: str,
    ) -> Proposal:
        done = self._replayed(request_id, proposal_id)
        if done is not None:
            return done
        p = self.proposal(proposal_id)
        if p.status != ProposalStatus.pending:
            raise AgentConflict("not_pending", f"{p.id} is {p.status.value}")
        if p.kind in (ProposalKind.attach, ProposalKind.regroup):
            raise InvalidOp("attach and regroup proposals are changed in Verify, not edited here")
        slug = target_slug(p.target_id)
        follow: list[RunPlanIn] = []
        with self.store.tx():
            p = self._claim(p.id)
            if p.kind == ProposalKind.bbox:
                if bbox is None:
                    raise InvalidOp("a bbox proposal is edited with a bbox")
                meta = {"proposal": p.model_dump(mode="json"), "proposal_id": p.id}
                self.figures.set_bbox(
                    p.target_id, list(bbox), request_id, screen="agent", meta=meta
                )
                act = self.store.action_by_request(request_id)
                assert act is not None
                self.store.resolve_flag(p.flag_id, f"proposal {p.id} edited", act.id)
                self._settle(p, ProposalStatus.edited, act.id, final_bbox=[float(v) for v in bbox])
                follow.append(RunPlanIn(to="score2", docs=[slug], force=["figures"]))
            else:
                if text is None:
                    raise InvalidOp("a text proposal is edited with text")
                out = self.review.apply_proposal_edit(
                    p.target_id, text, p, confirm_content_change, request_id
                )
                self._settle(p, ProposalStatus.edited, out.action_id, final_text=text)
        self._follow_up(follow)
        return self.proposal(proposal_id)

    def reject(self, proposal_id: str, reason: str | None, request_id: str) -> Proposal:
        done = self._replayed(request_id, proposal_id)
        if done is not None:
            return done
        p = self.proposal(proposal_id)
        if p.status != ProposalStatus.pending:
            raise AgentConflict("not_pending", f"{p.id} is {p.status.value}")
        slug = target_slug(p.target_id)
        with self.store.tx():
            p = self._claim(p.id)
            aid = self.store.next_action_id()
            self.store.append_action(
                ActionKind.proposal_reject,
                "agent",
                target_id=p.target_id,
                doc_id=slug,
                payload={
                    "proposal_id": p.id,
                    "flag_id": p.flag_id,
                    "reason": reason,
                    "failed_checks": [r.check for r in p.rechecks if not r.passed],
                    "_outcome": p.id,
                },
                example={"proposal": p.model_dump(mode="json"), "reason": reason},
                request_id=request_id,
                action_id=aid,
            )
            self._settle(p, ProposalStatus.rejected, aid)
        # the flag stays open: the block is back in the agent queue and in Verify's flagged count
        return self.proposal(proposal_id)

    def accept_all_passing(self, docs: Sequence[str] | None, request_id: str) -> list[Proposal]:
        """Accept every pending proposal whose checks all passed, whose basis is fresh and
        whose target is not a numeric-spec block. Numeric blocks always need an individual
        accept (SPEC 5.1)."""
        accepted: list[Proposal] = []
        for p in self.store.proposals(status=ProposalStatus.accepted):
            aid = self.store.proposal_row_action(p.id)
            act = self.store.get_action(aid) if aid is not None else None
            if act is not None and (act.request_id or "").startswith(f"{request_id}:"):
                accepted.append(p)
        follow: list[RunPlanIn] = []
        for p in self.store.proposals(status=ProposalStatus.pending):
            slug = target_slug(p.target_id)
            if docs is not None and slug not in docs:
                continue
            if not p.all_checks_passed or not self._fresh(p) or self._numeric_target(p):
                continue
            try:
                follow.extend(self._accept(p, f"{request_id}:{p.id}", bulk=True))
            except AgentConflict as exc:
                if exc.code in ("already_decided", "not_pending", "stale_proposal"):
                    continue  # decided or superseded meanwhile: not this bulk's to accept
                raise
            accepted.append(self.proposal(p.id))
        self._follow_up(follow)
        return sorted(accepted, key=lambda x: x.id)

    def _numeric_target(self, p: Proposal) -> bool:
        slug = target_slug(p.target_id)
        block_id = p.target_id
        if p.target_id.startswith("FIG-"):
            return False
        blk = next((b for b in self.data.machine_blocks(slug) if b.id == block_id), None)
        if blk is None:
            return True
        if blk.type == BlockType.figure:
            return False
        if blk.has_numeric_spec:
            return True
        if p.kind in (ProposalKind.text, ProposalKind.cells) and p.proposal_text is not None:
            # by position: a permutation of the same numbers is a numeric change
            return numbers_changed(blk.raw_text, p.proposal_text)
        return False
