"""Agent pass and calibration (design 10 section 6). No route calls a model: proposals come
from a job, accept re-uses the rechecks stored with the proposal."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from manuallabor.agent.service import AgentItemView
from manuallabor.api.deps import Ctx
from manuallabor.api.errors import ApiError
from manuallabor.api.models import (
    AcceptAllIn,
    AgentRunIn,
    ApiErrorBody,
    CalibrationApplyIn,
    CalibrationApplyOut,
    ProposalEditIn,
    ProposalRejectIn,
    RequestIn,
)
from manuallabor.contracts.enums import ProposalStatus
from manuallabor.contracts.proposal import Proposal
from manuallabor.state.models import CalibrationReport, JobInfo

router = APIRouter(
    prefix="/api",
    tags=["agent"],
    responses={409: {"model": ApiErrorBody}, 422: {"model": ApiErrorBody}},
)


def _agent(ctx: Ctx):  # type: ignore[no-untyped-def]
    if ctx.agent is None:
        raise ApiError(503, "no_agent", "the agent service is not available")
    return ctx.agent


def _rid(body: RequestIn | None) -> str:
    return (body or RequestIn()).request_id


@router.post("/agent/run", status_code=202, response_model=JobInfo)
def agent_run(ctx: Ctx, body: AgentRunIn | None = None) -> JobInfo:
    b = body or AgentRunIn()
    job: JobInfo = _agent(ctx).enqueue(b.docs, b.flag_ids, b.request_id)
    return job


@router.get("/agent/items", response_model=list[AgentItemView])
def list_items(ctx: Ctx) -> list[AgentItemView]:
    out: list[AgentItemView] = _agent(ctx).items()
    return out


@router.get("/agent/proposals", response_model=list[Proposal])
def list_proposals(
    ctx: Ctx,
    status: ProposalStatus | None = None,
    flag_id: Annotated[str | None, Query(pattern=r"^flag-\d{6}$")] = None,
    doc: str | None = None,
) -> list[Proposal]:
    out: list[Proposal] = _agent(ctx).proposals(status, flag_id, doc)
    return out


@router.post("/agent/proposals/{proposal_id}/accept", response_model=Proposal)
def accept_proposal(proposal_id: str, ctx: Ctx, body: RequestIn | None = None) -> Proposal:
    out: Proposal = _agent(ctx).accept(proposal_id, _rid(body))
    return out


@router.post("/agent/proposals/{proposal_id}/edit", response_model=Proposal)
def edit_proposal(proposal_id: str, body: ProposalEditIn, ctx: Ctx) -> Proposal:
    out: Proposal = _agent(ctx).edit(
        proposal_id,
        text=body.text,
        bbox=None if body.bbox is None else list(body.bbox),
        confirm_content_change=body.confirm_content_change,
        request_id=body.request_id,
    )
    return out


@router.post("/agent/proposals/{proposal_id}/reject", response_model=Proposal)
def reject_proposal(proposal_id: str, ctx: Ctx, body: ProposalRejectIn | None = None) -> Proposal:
    b = body or ProposalRejectIn()
    out: Proposal = _agent(ctx).reject(proposal_id, b.reason, b.request_id)
    return out


@router.post("/agent/accept-all-passing", response_model=list[Proposal])
def accept_all_passing(ctx: Ctx, body: AcceptAllIn | None = None) -> list[Proposal]:
    b = body or AcceptAllIn()
    out: list[Proposal] = _agent(ctx).accept_all_passing(b.docs, b.request_id)
    return out


@router.get("/calibration", response_model=CalibrationReport)
def get_calibration(
    ctx: Ctx,
    scope: Literal["project", "global"] = "project",
    snapshot: str | None = None,
) -> CalibrationReport:
    if ctx.calibration is None:
        raise ApiError(503, "no_calibration", "the calibration service is not available")
    out: CalibrationReport = ctx.calibration.report(scope, snapshot)
    return out


@router.post("/calibration/apply", response_model=CalibrationApplyOut)
def apply_calibration(body: CalibrationApplyIn, ctx: Ctx) -> CalibrationApplyOut:
    if ctx.calibration is None:
        raise ApiError(503, "no_calibration", "the calibration service is not available")
    thr, pinned, job = ctx.calibration.apply(body.threshold, body.scope, body.request_id)
    return CalibrationApplyOut(threshold=thr, scope=body.scope, pinned=pinned, job=job)
