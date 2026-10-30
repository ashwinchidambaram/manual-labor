"""FastAPI application factory (design 07 sections 5.1, 7)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

import manuallabor
from manuallabor.api.deps import Hooks
from manuallabor.api.errors import ApiError, install_handlers
from manuallabor.api.guard import DEFAULT_MAX_BODY_BYTES, RequestGuard
from manuallabor.api.routers import (
    agent,
    export,
    figures,
    jobs,
    learning,
    project,
    scope,
    sources,
    ui,
    verify,
)
from manuallabor.state.interfaces import AppServices

NOT_BUILT_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Manual Labor</title></head>"
    "<body><h1>Manual Labor</h1><p>frontend not built: "
    "<code>cd frontend &amp;&amp; npm run build</code></p></body></html>"
)


def _unique_id(route: APIRoute) -> str:
    return route.name


def create_app(
    ctx: AppServices | None,
    *,
    static_dir: Path | None = None,
    dev: bool = False,
    hooks: Hooks | None = None,
    allowed_hosts: Iterable[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> FastAPI:
    """Build the app. `ctx=None` is for OpenAPI export (every route answers 503).

    Every request passes `RequestGuard` (design 07 section 15): same-origin writes and the body
    cap always; the Host allow-list when `allowed_hosts` is given (`labor serve` always does)."""
    app = FastAPI(
        title="Manual Labor API",
        version=manuallabor.__version__,
        generate_unique_id_function=_unique_id,
        separate_input_output_schemas=False,
    )
    app.state.ctx = ctx
    app.state.hooks = hooks or Hooks()
    app.state.max_body_bytes = max_body_bytes
    app.add_middleware(
        RequestGuard,
        allowed_hosts=None if allowed_hosts is None else frozenset(allowed_hosts),
        max_body_bytes=max_body_bytes,
    )
    install_handlers(app)
    for r in (project, sources, scope, verify, figures, jobs, learning, agent, export, ui):
        app.include_router(r.router)
    _mount_frontend(app, static_dir, dev)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path | None, dev: bool) -> None:
    index = static_dir / "index.html" if static_dir is not None else None
    if static_dir is not None and not dev and (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> Response:
        if dev or full_path == "api" or full_path.startswith(("api/", "assets/")):
            raise ApiError(404, "not_found", f"no such route: /{full_path}")
        if index is not None and index.is_file():
            if full_path:
                candidate = (static_dir / full_path).resolve() if static_dir else None
                if (
                    candidate is not None
                    and static_dir is not None
                    and candidate.is_file()
                    and candidate.is_relative_to(static_dir.resolve())
                ):
                    return FileResponse(candidate)
            return FileResponse(index, media_type="text/html")
        if full_path == "":
            return HTMLResponse(NOT_BUILT_HTML)
        raise ApiError(404, "not_found", f"no such route: /{full_path}")
