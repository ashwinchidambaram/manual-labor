"""API error type and the exception -> HTTP mapping (design 07 sections 5.1, 11.2)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from manuallabor.state.errors import (
    EditConflictError,
    InvalidOp,
    LockHeld,
    NoPageRender,
    OutOfScope,
    StateError,
)


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

    @app.exception_handler(LockHeld)
    async def _lock(_: Request, exc: LockHeld) -> JSONResponse:
        return _json(409, "locked", str(exc))

    @app.exception_handler(OutOfScope)
    async def _scope(_: Request, exc: OutOfScope) -> JSONResponse:
        return _json(422, "out_of_scope", str(exc))

    @app.exception_handler(InvalidOp)
    async def _invalid(_: Request, exc: InvalidOp) -> JSONResponse:
        return _json(422, "invalid_op", str(exc))

    @app.exception_handler(NoPageRender)
    async def _norender(_: Request, exc: NoPageRender) -> JSONResponse:
        return _json(404, "no_page_render", str(exc) or "no page render for this document")

    @app.exception_handler(KeyError)
    async def _missing(_: Request, exc: KeyError) -> JSONResponse:
        what = exc.args[0] if exc.args else "resource"
        return _json(404, "not_found", f"not found: {what}")

    @app.exception_handler(StateError)
    async def _state(_: Request, exc: StateError) -> JSONResponse:
        return _json(500, "state_error", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return _json(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = [
            f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg', '')}"
            for e in exc.errors()
        ]
        return _json(422, "validation_error", "; ".join(parts))
