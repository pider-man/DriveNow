"""Map errors to HTTP responses with one JSON shape: ``{"error": {"code", "message"}}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from drivenow.domain.exceptions import (
    VALIDATION_ERROR,
    BusinessRuleViolation,
    DomainError,
    InvalidInputError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

DOMAIN_STATUS: list[tuple[type[DomainError], int]] = [
    (NotFoundError, 404),
    (BusinessRuleViolation, 409),
    (InvalidInputError, 422),
]

HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _domain_status(exc: DomainError) -> int:
    for exc_type, status_code in DOMAIN_STATUS:
        if isinstance(exc, exc_type):
            return status_code
    return 400


def _describe_validation_errors(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts) or "Invalid request"


def register_error_handlers(app: FastAPI) -> None:
    """Install the exception handlers on ``app``."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # The service has already logged the rejection at WARNING.
        return error_response(_domain_status(exc), exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        message = _describe_validation_errors(exc)
        logger.warning("%s %s rejected: %s: %s", request.method, request.url.path, VALIDATION_ERROR, message)
        return error_response(422, VALIDATION_ERROR, message)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        response = error_response(exc.status_code, code, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "INTERNAL_ERROR", "Internal server error")
