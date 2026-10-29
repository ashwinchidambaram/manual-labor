"""Agent pass and calibration: 501 stubs with the final contract shape (module 10)."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter

from manuallabor.api.errors import not_implemented
from manuallabor.api.models import (
    AgentRunIn,
    ApiErrorBody,
    CalibrationApplyIn,
    CalibrationApplyOut,
    ProposalEditIn,
    RequestIn,
)
from manuallabor.contracts.proposal import Proposal
from manuallabor.state.models import CalibrationReport, JobInfo

router = APIRouter(prefix="/api", tags=["agent"], responses={501: {"model": ApiErrorBody}})


def _stub() -> NoReturn:
    raise not_implemented("module 10")


@router.post("/agent/run", status_code=202, response_model=JobInfo)
def agent_run(body: AgentRunIn | None = None) -> JobInfo:
    _stub()


@router.get("/agent/proposals", response_model=list[Proposal])
def list_proposals() -> list[Proposal]:
    _stub()


@router.post("/agent/proposals/{proposal_id}/accept", response_model=Proposal)
def accept_proposal(proposal_id: str, body: RequestIn | None = None) -> Proposal:
    _stub()


@router.post("/agent/proposals/{proposal_id}/edit", response_model=Proposal)
def edit_proposal(proposal_id: str, body: ProposalEditIn) -> Proposal:
    _stub()


@router.post("/agent/proposals/{proposal_id}/reject", response_model=Proposal)
def reject_proposal(proposal_id: str, body: RequestIn | None = None) -> Proposal:
    _stub()


@router.post("/agent/accept-all-passing", response_model=list[Proposal])
def accept_all_passing(body: RequestIn | None = None) -> list[Proposal]:
    _stub()


@router.get("/calibration", response_model=CalibrationReport)
def get_calibration() -> CalibrationReport:
    _stub()


@router.post("/calibration/apply", response_model=CalibrationApplyOut)
def apply_calibration(body: CalibrationApplyIn) -> CalibrationApplyOut:
    _stub()
