"""Verify screen: queue, cursor, block detail, actions, flags (design 07 section 5.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from manuallabor.api.deps import Ctx
from manuallabor.api.models import ApiErrorBody, CursorIn, EditConflictBody, ResolveFlagIn
from manuallabor.contracts.enums import FlagStatus
from manuallabor.contracts.flag import Flag
from manuallabor.state.models import (
    BlockDetail,
    Cursor,
    QueuePage,
    QueueSort,
    ReviewActionIn,
    ReviewActionOut,
)

router = APIRouter(prefix="/api", tags=["verify"])


@router.get("/verify/queue", response_model=QueuePage)
def get_queue(
    ctx: Ctx,
    sort: QueueSort | None = None,
    view_threshold: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    doc: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QueuePage:
    """`view_threshold` is a view filter for this read only; it never approves anything."""
    return ctx.review.queue(sort, view_threshold, doc, limit, offset)


@router.get("/verify/cursor", response_model=Cursor)
def get_cursor(ctx: Ctx) -> Cursor:
    return ctx.review.cursor()


@router.put("/verify/cursor", response_model=Cursor)
def put_cursor(body: CursorIn, ctx: Ctx) -> Cursor:
    current = ctx.review.cursor()
    merged = Cursor(
        sort=body.sort,
        view_threshold=body.view_threshold,
        doc_filter=body.doc_filter,
        current_block_id=body.current_block_id,
        trail=current.trail,
    )
    return ctx.review.set_cursor(merged, body.request_id)


@router.get(
    "/verify/blocks/{block_id}",
    response_model=BlockDetail,
    responses={404: {"model": ApiErrorBody}, 422: {"model": ApiErrorBody}},
)
def get_block(block_id: str, ctx: Ctx) -> BlockDetail:
    return ctx.review.detail(block_id)


@router.post(
    "/verify/actions",
    response_model=ReviewActionOut,
    responses={409: {"model": EditConflictBody}, 422: {"model": ApiErrorBody}},
)
def post_action(body: ReviewActionIn, ctx: Ctx) -> ReviewActionOut:
    """Approve / edit / flag / skip / back. An edit that fails the faithfulness check is a
    409 `edit_conflict` carrying the diff; re-send with `confirm_content_change=true` to store
    it as a human edit."""
    return ctx.review.act(body)


@router.get("/flags", response_model=list[Flag])
def get_flags(ctx: Ctx, status: FlagStatus | None = FlagStatus.open) -> list[Flag]:
    return ctx.review.flags(status)


@router.post("/flags/{flag_id}/resolve", response_model=Flag)
def resolve_flag(flag_id: str, body: ResolveFlagIn, ctx: Ctx) -> Flag:
    return ctx.review.resolve_flag(flag_id, body.resolution, body.request_id)
