"""Application errors and the handlers that render them as
`{"error": {"code", "message", "details"}}`."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)

_LOC_PREFIXES = {"body", "query", "path", "header", "cookie"}


class AppError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"
    message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or []
        self.headers = headers
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Resource not found"


class UnauthenticatedError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "Forbidden"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "Conflict"


class ValidationFailed(AppError):
    """Business-rule validation (rendered exactly like a 422 from pydantic)."""

    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Request validation failed"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(details=[{"field": field, "message": message}])


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests, try again in a minute"


# ---- OpenAPI error models -------------------------------------------------------------


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` helper so `/docs` documents the error shape."""
    return {c: {"model": ErrorResponse, "description": HTTPStatus(c).phrase} for c in codes}


# ---- handlers --------------------------------------------------------------------------


def error_payload(code: str, message: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def _field_from_loc(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = list(loc)
    if parts and parts[0] in _LOC_PREFIXES:
        parts = parts[1:]
    return ".".join(str(p) for p in parts)


def _status_code_name(status: int) -> str:
    try:
        return HTTPStatus(status).phrase.upper().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "HTTP_ERROR"


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_payload(exc.code, exc.message, exc.details),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"field": _field_from_loc(err.get("loc", ())), "message": str(err.get("msg", ""))}
        for err in exc.errors()
    ]
    return JSONResponse(
        error_payload("VALIDATION_ERROR", "Request validation failed", details),
        status_code=422,
    )


async def http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = "NOT_FOUND" if exc.status_code == 404 else _status_code_name(exc.status_code)
    if exc.status_code == 413:
        code = "PAYLOAD_TOO_LARGE"
    message = exc.detail if isinstance(exc.detail, str) else _status_code_name(exc.status_code)
    return JSONResponse(
        error_payload(code, message),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", error_type=type(exc).__name__)
    return JSONResponse(
        error_payload("INTERNAL_ERROR", "Something went wrong"),
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
