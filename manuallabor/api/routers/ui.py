"""Per-project UI state (design 12 section 3). Stored in the `meta` table only: never an action,
never part of decisions, calibration, learning snapshots or any export byte."""

from __future__ import annotations

import json

from fastapi import APIRouter

from manuallabor.api.deps import Ctx
from manuallabor.api.models import ApiErrorBody, GuideState, GuideStateIn

router = APIRouter(prefix="/api/ui", tags=["ui"])

GUIDE_KEY = "ui.guide_seen"
GUIDE_VERSION = 1


def _read(raw: str | None) -> GuideState:
    """Seen only when the stored version equals the current one (a bump shows the guide again)."""
    unseen = GuideState(seen=False, seen_at=None, version=GUIDE_VERSION)
    if not raw:
        return unseen
    try:
        data = json.loads(raw)
        stored = data["version"]
        at = data.get("seen_at")
    except (ValueError, KeyError, TypeError, AttributeError):
        return unseen
    if stored != GUIDE_VERSION or isinstance(stored, bool):
        return unseen
    return GuideState(seen=True, seen_at=at if isinstance(at, str) else None, version=GUIDE_VERSION)


@router.get("/guide", response_model=GuideState, responses={503: {"model": ApiErrorBody}})
def get_guide(ctx: Ctx) -> GuideState:
    return _read(ctx.store.meta(GUIDE_KEY))


@router.put(
    "/guide",
    response_model=GuideState,
    responses={422: {"model": ApiErrorBody}, 503: {"model": ApiErrorBody}},
)
def put_guide(body: GuideStateIn, ctx: Ctx) -> GuideState:
    with ctx.store.tx():
        if body.seen:
            value = json.dumps(
                {"version": GUIDE_VERSION, "seen_at": ctx.store.now()}, sort_keys=True
            )
        else:
            value = ""  # cleared (the store has no meta delete); _read treats "" as unseen
        ctx.store.set_meta(GUIDE_KEY, value)
    return _read(ctx.store.meta(GUIDE_KEY))
