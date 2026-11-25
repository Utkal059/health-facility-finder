"""One error format for every failure:

    {"error": {"code": "not_found", "message": "...", "details": ...}}
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("api")

_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
    503: "service_unavailable",
}


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: Any = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(
    status: int, code: str, message: str, details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _invalid_input(_: Request, exc: RequestValidationError):
        details = [
            {
                "parameter": ".".join(str(part) for part in err["loc"] if part != "query"),
                "problem": err["msg"],
            }
            for err in exc.errors()
        ]
        return error_response(400, "invalid_parameters", "Some parameters are not valid.", details)

    @app.exception_handler(psycopg.DataError)
    async def _unusable_value(_: Request, exc: psycopg.DataError):
        # Queries here only carry request parameters, so a value Postgres
        # can't hold (a NUL character, say) is the caller's mistake.
        log.info("Rejected parameter value: %s", exc)
        return error_response(400, "invalid_parameters", "A parameter has a value we can't search for.")

    @app.exception_handler(psycopg.OperationalError)
    async def _database_unavailable(_: Request, exc: psycopg.OperationalError):
        log.warning("Database unavailable: %s", exc)
        return error_response(503, "database_unavailable",
                              "The database is not reachable. Please try again in a moment.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        if exc.status_code == 404 and message == "Not Found":
            message = "There is nothing at this address."
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return error_response(500, "internal_error", "Something went wrong on our side.")
