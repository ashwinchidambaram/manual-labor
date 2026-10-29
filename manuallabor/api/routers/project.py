"""Project info, status, probe, config (design 07 section 5.3)."""

from __future__ import annotations

from fastapi import APIRouter

import manuallabor
from manuallabor.api.deps import Ctx, HooksDep
from manuallabor.api.errors import ApiError
from manuallabor.api.models import (
    ApiErrorBody,
    ApplyTierIn,
    ApplyTierOut,
    ProbeOut,
    ProjectInfo,
    ThresholdIn,
    ThresholdOut,
)
from manuallabor.contracts.io import read_json, write_json
from manuallabor.contracts.probe import ProbeResult
from manuallabor.state.models import ProjectStatus, RunPlanIn

router = APIRouter(prefix="/api", tags=["project"])


@router.get("/project", response_model=ProjectInfo)
def get_project(ctx: Ctx) -> ProjectInfo:
    return ProjectInfo(
        name=ctx.paths.load_config().name,
        root=str(ctx.paths.root),
        config=ctx.paths.load_config(),
        learning=ctx.learning.state(),
        mock=ctx.mock,
        tool_version=manuallabor.__version__,
    )


@router.get("/status", response_model=ProjectStatus)
def get_status(ctx: Ctx, hooks: HooksDep) -> ProjectStatus:
    return hooks.status(ctx.paths, ctx.runner)


def _probe_out(probe: ProbeResult) -> ProbeOut:
    from manuallabor.providers.probe import suggest

    return ProbeOut(probe=probe, suggestions=suggest(probe))


@router.get("/probe", response_model=ProbeOut, responses={404: {"model": ApiErrorBody}})
def get_probe(ctx: Ctx) -> ProbeOut:
    path = ctx.paths.root / "probe.json"
    if not path.is_file():
        raise ApiError(404, "no_probe", "no probe.json yet; POST /api/probe to run one")
    return _probe_out(read_json(path, ProbeResult))


@router.post("/probe", response_model=ProbeOut)
def run_probe(ctx: Ctx, hooks: HooksDep) -> ProbeOut:
    probe = hooks.probe(ctx.paths)
    write_json(ctx.paths.root / "probe.json", probe)
    return _probe_out(probe)


@router.post(
    "/config/apply-tier",
    response_model=ApplyTierOut,
    responses={404: {"model": ApiErrorBody}, 422: {"model": ApiErrorBody}},
)
def apply_tier(body: ApplyTierIn, ctx: Ctx, hooks: HooksDep) -> ApplyTierOut:
    from manuallabor.providers.probe import ApplyError, suggest
    from manuallabor.providers.probe import apply_tier as _apply

    path = ctx.paths.root / "probe.json"
    if not path.is_file():
        raise ApiError(404, "no_probe", "run a probe first (POST /api/probe)")
    probe = read_json(path, ProbeResult)
    try:
        _apply(ctx.paths.config, suggest(probe), body.tier, force=body.force, probe=probe)
    except ApplyError as exc:
        raise ApiError(422, "apply_tier", str(exc)) from exc
    status = hooks.status(ctx.paths, ctx.runner)
    stale = [n for d in status.docs for n in d.nodes if n.state != "fresh"]
    return ApplyTierOut(models=ctx.paths.load_config().models, stale=stale)


@router.put("/config/threshold", response_model=ThresholdOut)
def put_threshold(body: ThresholdIn, ctx: Ctx) -> ThresholdOut:
    value = ctx.scope.set_project_threshold(body.value, body.reason, body.request_id)
    job = ctx.runner.enqueue(RunPlanIn(to="score2"), request_id=body.request_id)
    return ThresholdOut(threshold=value, job=job)
