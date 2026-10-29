"""Background jobs: enqueue, poll, log, cancel (design 07 section 5.3)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from manuallabor.api.deps import Ctx
from manuallabor.state.models import JobInfo, RunPlanIn

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", status_code=202, response_model=JobInfo)
def post_job(plan: RunPlanIn, ctx: Ctx) -> JobInfo:
    return ctx.runner.enqueue(plan)


@router.get("", response_model=list[JobInfo])
def list_jobs(ctx: Ctx, status: Annotated[list[str] | None, Query()] = None) -> list[JobInfo]:
    return ctx.runner.list(set(status) if status else None)


@router.get("/{job_id}", response_model=JobInfo)
def get_job(job_id: str, ctx: Ctx) -> JobInfo:
    return ctx.runner.get(job_id)


@router.get("/{job_id}/log", response_model=list[dict[str, Any]])
def get_job_log(
    job_id: str,
    ctx: Ctx,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[dict[str, Any]]:
    return ctx.runner.log(job_id, after, limit)


@router.post("/{job_id}/cancel", response_model=JobInfo)
def cancel_job(job_id: str, ctx: Ctx) -> JobInfo:
    return ctx.runner.cancel(job_id)
