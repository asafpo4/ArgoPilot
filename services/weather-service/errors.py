"""Problem+json errors, in one fixed style: type, title, status, detail, code."""

import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("weather.errors")

# The code for each HTTP status we return. Any other status is an unexpected error (500).
CODE_BY_STATUS = {404: "NOT_FOUND", 405: "VALIDATION"}


class RequestError(Exception):
    """A request that breaks the request rules. Each problem is (field, message)."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        super().__init__("invalid request")
        self.problems = problems


class ForecastUnavailable(Exception):
    """No usable forecast right now. The caller may retry after `retry_after` seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("forecast unavailable")
        self.retry_after = retry_after


def problem_response(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    # Newer Python versions call 422 "Unprocessable Content". The contract uses "Unprocessable Entity",
    # so 422 always gets that title, whatever Python version runs the service.
    title = "Unprocessable Entity" if status == 422 else HTTPStatus(status).phrase
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
    }
    return JSONResponse(
        content=body,
        status_code=status,
        headers=headers,
        media_type="application/problem+json",
    )


def unexpected_response() -> JSONResponse:
    # The real error is never sent. No Retry-After: retrying a bug does not help.
    return problem_response(500, "UNAVAILABLE", "Internal server error")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = CODE_BY_STATUS.get(exc.status_code)
    if code is None:
        return unexpected_response()
    return problem_response(exc.status_code, code, str(exc.detail), exc.headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's own validation body never reaches a client. Messages name fields, never values.
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
    return problem_response(422, "VALIDATION", details)


async def request_error_handler(request: Request, exc: RequestError) -> JSONResponse:
    details = "; ".join(f"{field}: {message}" for field, message in exc.problems)
    return problem_response(422, "VALIDATION", details)


async def forecast_unavailable_handler(request: Request, exc: ForecastUnavailable) -> JSONResponse:
    return problem_response(
        503, "UNAVAILABLE", "Forecast unavailable", {"Retry-After": str(exc.retry_after)}
    )


class UnexpectedErrorMiddleware:
    """Turns an error the app did not handle into the 500 answer, and stops it there.

    Starlette's own handler for `Exception` sends the 500 and then re-raises the error, so a real
    server prints the traceback, and the traceback holds the exception's message. This middleware
    logs only the exception's class and returns the 500 itself, so nothing is re-raised.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception as exc:
            logger.error("Unexpected error: %s", type(exc).__name__)
            if not started:
                await unexpected_response()(scope, receive, send)


def install_handlers(app: FastAPI) -> None:
    handlers: dict[Any, Callable[[Request, Any], Awaitable[JSONResponse]]] = {
        StarletteHTTPException: http_exception_handler,
        RequestValidationError: validation_exception_handler,
        RequestError: request_error_handler,
        ForecastUnavailable: forecast_unavailable_handler,
    }
    for exception_class, handler in handlers.items():
        app.add_exception_handler(exception_class, handler)
    app.add_middleware(UnexpectedErrorMiddleware)
