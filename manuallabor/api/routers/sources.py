"""Sources, original files, page renders (design 07 section 5.3)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse

from manuallabor.api.deps import Ctx, HooksDep
from manuallabor.api.errors import ApiError
from manuallabor.api.guard import DEFAULT_MAX_BODY_BYTES
from manuallabor.api.models import ApiErrorBody, DocFigure, PageBlock, SourceInfo
from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockStatus, BlockType
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.io import PART_SUFFIX, read_json, read_json_list
from manuallabor.project import DocPaths, ProjectPaths
from manuallabor.state.models import FigureAttachment, JobInfo, RunPlanIn

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


def _save_upload(uploads: Path, f: UploadFile, limit: int = DEFAULT_MAX_BODY_BYTES) -> Path:
    """Stream one upload into `.uploads/<sha256>/<name>`. The temp file is unique per call (two
    uploads of one name may be in flight at once) and named `.incoming-*.part`: this runs outside
    the worker lock, and serve start-up removes leftovers (design 07 section 14.1). A file over
    `limit` bytes stops the copy with a 413 and leaves no temp file (section 15; the request
    guard caps the whole body before this runs, this is the per-file backstop)."""
    name = Path(f.filename or "").name
    if not name:
        raise ApiError(422, "bad_upload", "an uploaded file has no name")
    uploads.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(dir=uploads, prefix=".incoming-", suffix=PART_SUFFIX)
    tmp = Path(raw)
    try:
        h = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := f.file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise ApiError(
                        413, "too_large", f"{name} is larger than the upload limit of {limit} bytes"
                    )
                h.update(chunk)
                out.write(chunk)
        dest_dir = uploads / h.hexdigest()
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / name
        os.replace(tmp, dest)  # same bytes under the same name: last one wins, both are right
    finally:
        tmp.unlink(missing_ok=True)
    return dest


@router.post("/sources", status_code=202, response_model=JobInfo)
def upload_sources(
    request: Request, ctx: Ctx, files: Annotated[list[UploadFile], File()]
) -> JobInfo:
    if not files:
        raise ApiError(422, "bad_upload", "no files uploaded")
    limit = int(getattr(request.app.state, "max_body_bytes", DEFAULT_MAX_BODY_BYTES))
    saved = [_save_upload(ctx.paths.uploads, f, limit) for f in files]
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


@router.get("/docs/{slug}/figures", response_model=list[DocFigure])
def get_doc_figures(slug: str, ctx: Ctx) -> list[DocFigure]:
    """Every figure of the document with all of its attachments (articles), sorted by figure id."""
    # A document that is not scored yet has none to review: an empty list.
    # the file part (attachments, figure records) is cached on the files' stats and the statuses
    # come from one cached derivation of the document (review F5: this re-derived the whole
    # document once per figure page)
    _known_slug(ctx.paths, slug)
    from manuallabor.state.data import ProjectData, sig

    dp = ctx.paths.doc(slug)
    fig_files = sorted(ctx.paths.figure_dir(slug).glob("FIG-*.json"))
    data = getattr(ctx.review, "data", None)
    if isinstance(data, ProjectData):
        signature = sig(dp.attach, dp.blocks, *fig_files) + tuple(p.name for p in fig_files)
        figs: list[_FigRow] = data.memo(
            "doc_figures", slug, signature, lambda: _figure_rows(dp, fig_files)
        )
    else:
        figs = _figure_rows(dp, fig_files)
    if not figs:
        return []  # nothing to derive (review 2 finding 6)
    status = ctx.review.block_statuses(slug)
    if not status:
        return []  # not scored yet, or by another algo version (design 03 section 2.10a)
    out = [
        DocFigure(
            figure_id=rec.id,
            block_id=block_id,
            record=rec,
            image_url=f"/api/figures/{rec.id}/image",
            attachments=list(atts),
            status=status.get(block_id, BlockStatus.queued),
        )
        for rec, block_id, atts in figs
    ]
    return sorted(out, key=lambda f: f.figure_id)


_FigRow = tuple[FigureRecord, str, list[FigureAttachment]]


def _figure_rows(dp: DocPaths, fig_files: list[Path]) -> list[_FigRow]:
    """(record, figure block id, attachments) per figure record that has a figure block."""
    from manuallabor.cleanup.types import AttachFile

    attachments: dict[str, list[FigureAttachment]] = {}
    if dp.attach.is_file():
        af = read_json(dp.attach, AttachFile)
        for art in af.articles:
            for a in art.figures:
                attachments.setdefault(a.figure_id, []).append(
                    FigureAttachment(
                        article_id=art.article_id,
                        rule=a.rule.value,
                        confidence=a.confidence,
                        anchor_block_id=a.anchor_block_id,
                    )
                )
    blocks = read_json_list(dp.blocks, Block) if dp.blocks.is_file() else []
    block_of = {b.figure_id: b for b in blocks if b.type == BlockType.figure and b.figure_id}
    out: list[_FigRow] = []
    for path in fig_files:
        rec = read_json(path, FigureRecord)
        blk = block_of.get(rec.id)
        if blk is None:
            continue
        out.append((rec, blk.id, attachments.get(rec.id, [])))
    return out
