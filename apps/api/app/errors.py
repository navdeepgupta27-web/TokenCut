"""Single error envelope for the whole API.

Every failure — validation, rate limit, upstream, unhandled — leaves the
service in the same shape:

    {"error": {"code": ..., "message": ..., "details": {}, "request_id": ...}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("tokencut.errors")


class APIError(Exception):
    """Base for every error this service raises deliberately."""

    code = "internal_error"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidRequest(APIError):
    code = "invalid_request"
    http_status = status.HTTP_400_BAD_REQUEST


class UnsupportedModel(APIError):
    code = "unsupported_model"
    http_status = status.HTTP_400_BAD_REQUEST


class TextTooLarge(APIError):
    code = "text_too_large"
    http_status = 413  # int literal: the Starlette constant was renamed mid-4.x


class Unauthorized(APIError):
    """The shared internal token was missing or wrong.

    Only ever raised when ``settings.api_internal_token`` is configured. It
    exists because a publicly reachable backend is an open proxy to the
    operator's provider quota otherwise.
    """

    code = "unauthorized"
    http_status = status.HTTP_401_UNAUTHORIZED


class RateLimited(APIError):
    code = "rate_limited"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, message: str, *, retry_after: int = 60, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class UpstreamUnavailable(APIError):
    """A provider's counting endpoint failed.

    Raised only when there is no acceptable degraded path. Where an estimate is
    acceptable the tokenizer layer returns ``source="estimated"`` instead of
    raising — a partial answer beats a 502 for this product.
    """

    code = "upstream_unavailable"
    http_status = status.HTTP_502_BAD_GATEWAY


def _envelope(code: str, message: str, details: dict[str, Any], request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimited):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(exc.code, exc.message, exc.details, _request_id(request)),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,  # see note on TextTooLarge
            content=_envelope(
                "invalid_request",
                "Request body failed validation.",
                {"errors": exc.errors()},
                _request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the type and request id, never the request body — bodies are
        # user prompts and must not reach the logs.
        log.exception(
            "unhandled_exception",
            extra={"request_id": _request_id(request), "exc_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "internal_error",
                "An unexpected error occurred.",
                {},
                _request_id(request),
            ),
        )
