"""API error type and the exception -> HTTP mapping (design 07 sections 5.1, 11.2)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from manuallabor.agent.errors import AgentConflict
from manuallabor.state.errors import (
    EditConflictError,
    InvalidOp,
    LockHeld,
    NoPageRender,
    NotFound,
    OutOfScope,
    RequestIdReused,
    StateError,
)

log = logging.getLogger("manuallabor.api")


class ApiError(Exception):
    """Raised by routes; rendered as `{detail, code}`."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def not_implemented(module: str) -> ApiError:
    return ApiError(501, "not_implemented", f"not implemented yet ({module})")


def _json(status: int, code: str, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code, **extra}, status_code=status)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return _json(exc.status, exc.code, exc.detail)

    @app.exception_handler(EditConflictError)
    async def _conflict(_: Request, exc: EditConflictError) -> JSONResponse:
        return _json(
            409,
            "edit_conflict",
            str(exc),
            conflict=jsonable_encoder(exc.conflict.model_dump(mode="json")),
        )

    @app.exception_handler(AgentConflict)
    async def _agent(_: Request, exc: AgentConflict) -> JSONResponse:
        return _json(409, exc.code, exc.detail)

    @app.exception_handler(LockHeld)
    async def _lock(_: Request, exc: LockHeld) -> JSONResponse:
        return _json(409, "locked", str(exc))

    @app.exception_handler(RequestIdReused)
    async def _reused(_: Request, exc: RequestIdReused) -> JSONResponse:
        return _json(409, "request_id_reused", str(exc))

    @app.exception_handler(OutOfScope)
    async def _scope(_: Request, exc: OutOfScope) -> JSONResponse:
        return _json(422, "out_of_scope", str(exc))

    @app.exception_handler(InvalidOp)
    async def _invalid(_: Request, exc: InvalidOp) -> JSONResponse:
        return _json(422, "invalid_op", str(exc))

    @app.exception_handler(NoPageRender)
    async def _norender(_: Request, exc: NoPageRender) -> JSONResponse:
        return _json(404, "no_page_render", str(exc) or "no page render for this document")

    # Only the explicit not-found of the services: a plain KeyError is a bug and falls through
    # to `_unhandled` (design 07 section 15, code review F13).
    @app.exception_handler(NotFound)
    async def _missing(_: Request, exc: NotFound) -> JSONResponse:
        what = exc.args[0] if exc.args else "resource"
        return _json(404, "not_found", f"not found: {what}")

    @app.exception_handler(StateError)
    async def _state(_: Request, exc: StateError) -> JSONResponse:
        return _json(500, "state_error", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return _json(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Starlette re-raises after this response, so uvicorn logs the traceback as well.
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return _json(500, "internal_error", "internal server error; see the labor serve log")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = [
            f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg', '')}"
            for e in exc.errors()
        ]
        return _json(422, "validation_error", "; ".join(parts))
