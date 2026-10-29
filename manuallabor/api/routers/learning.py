"""Learning layer controls and the decision-log export (design 07 sections 5.3, 9)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from manuallabor.api.deps import Ctx
from manuallabor.api.models import LearningFlagsIn, RequestIn
from manuallabor.contracts.io import canonical_json
from manuallabor.state.models import LearningState, SnapshotInfo

router = APIRouter(prefix="/api", tags=["learning"])


def _rid(body: RequestIn | None) -> str:
    return (body or RequestIn()).request_id


@router.get("/learning", response_model=LearningState)
def get_learning(ctx: Ctx) -> LearningState:
    return ctx.learning.state()


@router.put("/learning", response_model=LearningState)
def put_learning(body: LearningFlagsIn, ctx: Ctx) -> LearningState:
    return ctx.learning.set_flags(
        body.enabled, body.use_global, body.contribute_global, body.request_id
    )


@router.post("/learning/snapshots", response_model=SnapshotInfo)
def create_snapshot(ctx: Ctx, body: RequestIn | None = None) -> SnapshotInfo:
    return ctx.learning.snapshot(_rid(body))


@router.get("/learning/snapshots", response_model=list[SnapshotInfo])
def list_snapshots(ctx: Ctx) -> list[SnapshotInfo]:
    return ctx.learning.state().snapshots


@router.post("/learning/activate/{snapshot_id}", response_model=LearningState)
def activate_snapshot(snapshot_id: str, ctx: Ctx, body: RequestIn | None = None) -> LearningState:
    return ctx.learning.activate(snapshot_id, _rid(body))


@router.post("/learning/rollback/{snapshot_id}", response_model=LearningState)
def rollback_snapshot(snapshot_id: str, ctx: Ctx, body: RequestIn | None = None) -> LearningState:
    """Rollback is activation of an earlier snapshot (design 07 section 9)."""
    return ctx.learning.activate(snapshot_id, _rid(body))


@router.post("/learning/reset", response_model=LearningState)
def reset_learning(ctx: Ctx, body: RequestIn | None = None) -> LearningState:
    return ctx.learning.reset(_rid(body))


@router.post("/learning/items/{item_id}/disable", response_model=SnapshotInfo)
def disable_item(item_id: str, ctx: Ctx, body: RequestIn | None = None) -> SnapshotInfo:
    return ctx.learning.disable_item(item_id, _rid(body))


@router.post("/learning/publish/{snapshot_id}", response_model=SnapshotInfo)
def publish_snapshot(snapshot_id: str, ctx: Ctx, body: RequestIn | None = None) -> SnapshotInfo:
    return ctx.learning.publish(snapshot_id, _rid(body))


@router.get(
    "/decisions/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {"schema": {"type": "string"}}}}},
)
def export_decisions(ctx: Ctx) -> StreamingResponse:
    def lines() -> Iterator[bytes]:
        for rec in ctx.store.iter_actions():
            yield canonical_json(rec) + b"\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
