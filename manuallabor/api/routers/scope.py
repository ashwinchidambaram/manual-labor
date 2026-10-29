"""Scope screen: groups, selection, summary, regroup, models (design 07 section 5.3)."""

from __future__ import annotations

from fastapi import APIRouter

from manuallabor.api.deps import Ctx
from manuallabor.api.models import (
    ConfirmIn,
    DocGroups,
    RegroupOut,
    ScopeBlockRow,
    ScopeBlocks,
    ScopeModels,
)
from manuallabor.contracts.selection import ScopeSummary
from manuallabor.state.models import JobInfo, RegroupIn, RunPlanIn, SelectionOp, SelectionOut

router = APIRouter(prefix="/api/scope", tags=["scope"])


@router.get("/groups", response_model=list[DocGroups])
def get_groups(ctx: Ctx, doc: str | None = None) -> list[DocGroups]:
    return [DocGroups.model_validate(g) for g in ctx.scope.groups(doc)]


@router.get("/blocks", response_model=list[ScopeBlocks])
def get_blocks(ctx: Ctx, doc: str | None = None) -> list[ScopeBlocks]:
    """Per-block type/status/numeric flag so the client can compute live counts (design 08 G1).
    Statuses follow the current threshold; docs that are not scored yet are omitted."""
    from manuallabor.scoring.pipeline import load_scored_blocks
    from manuallabor.scoring.types import ScoringError

    out: list[ScopeBlocks] = []
    for slug in sorted(ctx.paths.list_slugs()):
        if doc is not None and slug != doc:
            continue
        if not ctx.paths.doc(slug).scores.is_file():
            continue
        try:
            scored = load_scored_blocks(ctx.paths, slug)
        except ScoringError:
            continue  # stale scores: the doc is still re-scoring
        rows = [
            ScopeBlockRow(id=b.id, type=b.type, status=b.status, numeric=b.has_numeric_spec)
            for b in scored
        ]
        out.append(ScopeBlocks(doc_id=slug, blocks=rows))
    return out


@router.get("/selection", response_model=SelectionOut)
def get_selection(ctx: Ctx) -> SelectionOut:
    return ctx.scope.get()


@router.put("/selection", response_model=SelectionOut)
def put_selection(op: SelectionOp, ctx: Ctx) -> SelectionOut:
    return ctx.scope.apply(op)


@router.get("/summary", response_model=ScopeSummary)
def get_summary(ctx: Ctx) -> ScopeSummary:
    return ctx.scope.summary()


@router.post("/regroup", status_code=202, response_model=RegroupOut)
def post_regroup(body: RegroupIn, ctx: Ctx) -> RegroupOut:
    override = ctx.scope.regroup(body)
    job = ctx.runner.enqueue(RunPlanIn(to="group", docs=[body.doc_id]))
    return RegroupOut(override=override, job=job)


@router.get("/models", response_model=ScopeModels)
def get_models(ctx: Ctx) -> ScopeModels:
    return ScopeModels.model_validate(ctx.scope.models())


@router.post("/confirm", status_code=202, response_model=JobInfo)
def post_confirm(ctx: Ctx, body: ConfirmIn | None = None) -> JobInfo:
    return ctx.runner.enqueue(RunPlanIn(to="score2"))
