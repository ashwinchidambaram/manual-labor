"""Figure rail: list, image, attach/detach, crop adjust (design 07 section 5.3)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from manuallabor import ids
from manuallabor.api.deps import Ctx
from manuallabor.api.errors import ApiError
from manuallabor.api.models import AttachIn, AttachOut, BboxIn, BboxOut
from manuallabor.state.models import FigureRailItem, RunPlanIn

router = APIRouter(prefix="/api", tags=["figures"])

_MEDIA = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _slug(fid: str) -> str:
    try:
        return ids.parse_figure_id(fid)[0]
    except ValueError as exc:
        raise ApiError(422, "bad_figure_id", f"not a figure id: {fid}") from exc


@router.get("/articles/{article_id}/figures", response_model=list[FigureRailItem])
def get_rail(article_id: str, ctx: Ctx) -> list[FigureRailItem]:
    return ctx.figures.rail(article_id)


@router.get("/figures/{fid}/image", response_class=FileResponse)
def get_figure_image(fid: str, ctx: Ctx) -> FileResponse:
    path = ctx.figures.image_path(fid)
    return FileResponse(
        path, media_type=_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    )


@router.post("/figures/{fid}/attach", status_code=202, response_model=AttachOut)
def attach_figure(fid: str, body: AttachIn, ctx: Ctx) -> AttachOut:
    slug = _slug(fid)
    override = ctx.figures.attach(fid, body.article_id, body.anchor_block_id, body.request_id)
    job = ctx.runner.enqueue(RunPlanIn(to="score2", docs=[slug]))
    return AttachOut(override=override, job=job)


@router.post("/figures/{fid}/detach", status_code=202, response_model=AttachOut)
def detach_figure(fid: str, body: AttachIn, ctx: Ctx) -> AttachOut:
    slug = _slug(fid)
    override = ctx.figures.detach(fid, body.article_id, body.request_id)
    job = ctx.runner.enqueue(RunPlanIn(to="score2", docs=[slug]))
    return AttachOut(override=override, job=job)


@router.put("/figures/{fid}/bbox", status_code=202, response_model=BboxOut)
def put_bbox(fid: str, body: BboxIn, ctx: Ctx) -> BboxOut:
    slug = _slug(fid)
    ctx.figures.set_bbox(fid, list(body.bbox), body.request_id)
    job = ctx.runner.enqueue(RunPlanIn(to="score2", docs=[slug], force=["figures"]))
    return BboxOut(job=job)
