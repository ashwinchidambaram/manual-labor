"""Export: real status (open flags), stubbed build (module 11)."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter

from manuallabor.api.deps import Ctx
from manuallabor.api.errors import not_implemented
from manuallabor.api.models import ApiErrorBody, OverrideIn, RequestIn
from manuallabor.state.models import ExportStatus, JobInfo

router = APIRouter(prefix="/api/export", tags=["export"])


def _stub() -> NoReturn:
    raise not_implemented("module 11")


@router.get("/status", response_model=ExportStatus)
def export_status(ctx: Ctx) -> ExportStatus:
    n = ctx.store.open_flag_count()
    return ExportStatus(unlocked=n == 0, open_flags=n, overrides=[])


@router.post("", status_code=202, response_model=JobInfo, responses={501: {"model": ApiErrorBody}})
def start_export(body: RequestIn | None = None) -> JobInfo:
    _stub()


@router.post("/override", response_model=ExportStatus, responses={501: {"model": ApiErrorBody}})
def export_override(body: OverrideIn) -> ExportStatus:
    _stub()
