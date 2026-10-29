"""Sources, original files, page renders (design 07 section 5.3)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse

from manuallabor.api.deps import Ctx, HooksDep
from manuallabor.api.errors import ApiError
from manuallabor.api.models import ApiErrorBody, PageBlock, SourceInfo
from manuallabor.project import ProjectPaths
from manuallabor.state.models import JobInfo, RunPlanIn

router = APIRouter(prefix="/api", tags=["sources"])


def _known_slug(paths: ProjectPaths, slug: str) -> None:
    if slug not in paths.list_slugs():
        raise ApiError(404, "not_found", f"unknown document: {slug}")


@router.get("/sources", response_model=list[SourceInfo])
def list_sources(ctx: Ctx, hooks: HooksDep) -> list[SourceInfo]:
    status = {d.doc_id: d for d in hooks.status(ctx.paths, ctx.runner).docs}
    out: list[SourceInfo] = []
    for doc in ctx.paths.list_documents():
        st = status.get(doc.slug)
        n = len(doc.pages_without_text_layer)
        out.append(
            SourceInfo(
                slug=doc.slug,
                filename=doc.filename,
                kind=doc.kind,
                pages=doc.page_count,
                ocr_warning=f"{n} page(s) without a text layer; OCR text is less reliable"
                if n
                else None,
                nodes=st.nodes if st else [],
            )
        )
    return out


def _save_upload(uploads: Path, f: UploadFile) -> Path:
    name = Path(f.filename or "").name
    if not name:
        raise ApiError(422, "bad_upload", "an uploaded file has no name")
    uploads.mkdir(parents=True, exist_ok=True)
    tmp = uploads / f".incoming-{hashlib.sha256(name.encode()).hexdigest()[:12]}"
    h = hashlib.sha256()
    with tmp.open("wb") as out:
        while chunk := f.file.read(1 << 20):
            h.update(chunk)
            out.write(chunk)
    dest_dir = uploads / h.hexdigest()
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / name
    shutil.move(str(tmp), dest)
    return dest


@router.post("/sources", status_code=202, response_model=JobInfo)
def upload_sources(ctx: Ctx, files: Annotated[list[UploadFile], File()]) -> JobInfo:
    if not files:
        raise ApiError(422, "bad_upload", "no files uploaded")
    saved = [_save_upload(ctx.paths.uploads, f) for f in files]
    return ctx.runner.enqueue(RunPlanIn(to="group"), kind="ingest_run", files=saved)


@router.get("/docs/{slug}/source", response_class=FileResponse)
def get_source(slug: str, ctx: Ctx) -> FileResponse:
    _known_slug(ctx.paths, slug)
    doc = ctx.paths.load_document(slug)
    path = ctx.paths.source(doc.filename)
    if not path.is_file():
        raise ApiError(404, "not_found", f"source file missing: {doc.filename}")
    return FileResponse(path, filename=doc.filename)


@router.get(
    "/docs/{slug}/pages/{page}.png",
    response_class=FileResponse,
    responses={404: {"model": ApiErrorBody}, 200: {"content": {"image/png": {}}}},
)
def get_page_png(
    slug: str, page: int, ctx: Ctx, dpi: Annotated[int, Query(ge=36, le=400)] = 150
) -> FileResponse:
    _known_slug(ctx.paths, slug)
    return FileResponse(ctx.review.render_page(slug, page, dpi), media_type="image/png")


@router.get("/docs/{slug}/pages/{page}/blocks", response_model=list[PageBlock])
def get_page_blocks(slug: str, page: int, ctx: Ctx) -> list[PageBlock]:
    _known_slug(ctx.paths, slug)
    return [PageBlock.model_validate(b) for b in ctx.review.page_blocks(slug, page)]
