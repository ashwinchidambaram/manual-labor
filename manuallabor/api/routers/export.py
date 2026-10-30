"""Export: gate status, override, build job and download (design 11 section 6)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from manuallabor.api.deps import Ctx
from manuallabor.api.errors import ApiError, not_implemented
from manuallabor.api.models import ApiErrorBody, OverrideIn, RequestIn
from manuallabor.state.models import ExportStatus, JobInfo, RunPlanIn
from manuallabor.state.store import Store

router = APIRouter(prefix="/api/export", tags=["export"])


def _store(ctx: Ctx) -> Store | None:
    """The real project store; the in-memory fakes of the API tests are not one."""
    return ctx.store if isinstance(ctx.store, Store) else None


def _status(ctx: Ctx) -> ExportStatus:
    store = _store(ctx)
    if store is None:
        n = ctx.store.open_flag_count()
        return ExportStatus(unlocked=n == 0, open_flags=n, overrides=[])
    from manuallabor.export.pipeline import export_status
    from manuallabor.state.review import ReviewService

    # the serving ReviewService: its cache makes an unchanged poll a dictionary read (review F4)
    review = ctx.review if isinstance(ctx.review, ReviewService) else None
    return export_status(ctx.paths, store, review)


@router.get("/status", response_model=ExportStatus)
def get_export_status(ctx: Ctx) -> ExportStatus:
    return _status(ctx)


@router.post(
    "",
    status_code=202,
    response_model=JobInfo,
    responses={409: {"model": ApiErrorBody}, 501: {"model": ApiErrorBody}},
)
def start_export(ctx: Ctx, body: RequestIn | None = None) -> JobInfo | JSONResponse:
    if _store(ctx) is None:
        raise not_implemented("module 11")
    st = _status(ctx)
    if st.blockers:
        return JSONResponse(
            {
                "detail": f"export is locked: {st.open_flags} open flag(s), "
                f"{st.queued} queued block(s)",
                "code": "export_locked",
                "open_flags": st.open_flags,
                "queued": st.queued,
                "blockers": st.blockers,
            },
            status_code=409,
        )
    for job in ctx.runner.list({"queued", "running"}):
        if job.kind == "export":
            return job
    return ctx.runner.enqueue(RunPlanIn(to="export"), kind="export")


@router.post(
    "/override",
    response_model=ExportStatus,
    responses={422: {"model": ApiErrorBody}, 501: {"model": ApiErrorBody}},
)
def export_override(body: OverrideIn, ctx: Ctx) -> ExportStatus:
    store = _store(ctx)
    if store is None:
        raise not_implemented("module 11")
    from manuallabor.export.pipeline import record_override

    record_override(
        ctx.paths,
        store,
        body.reason,
        target_id=body.target_id,
        flag_id=body.flag_id,
        request_id=body.request_id,
    )
    return _status(ctx)


@router.get("/download", responses={404: {"model": ApiErrorBody}})
def download_export(ctx: Ctx) -> FileResponse:
    from manuallabor.export.pipeline import read_state

    st = read_state(ctx.paths).export
    if st is None or not Path(st.zip_path).is_file():
        raise ApiError(404, "no_export", "nothing has been exported yet")
    return FileResponse(
        st.zip_path,
        media_type="application/zip",
        filename=Path(st.zip_path).name,
        headers={"X-Content-SHA256": st.summary.zip_sha256},
    )
