import sqlite3
from http import HTTPStatus

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# The code for each HTTP status we return. Any other status raises KeyError,
# and the unexpected error handler turns it into a 500.
CODE_BY_STATUS = {404: "NOT_FOUND", 405: "VALIDATION", 409: "CONFLICT", 422: "VALIDATION"}


def problem_response(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    # Newer Python versions call 422 "Unprocessable Content". The task uses "Unprocessable Entity",
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


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = CODE_BY_STATUS[exc.status_code]
    return problem_response(exc.status_code, code, str(exc.detail), exc.headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors())
    return problem_response(422, "VALIDATION", details)


async def database_unavailable_handler(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
    # The raw sqlite message is not sent to the client.
    return problem_response(503, "UNAVAILABLE", "Database unavailable", {"Retry-After": "5"})


async def invalid_text_handler(request: Request, exc: UnicodeEncodeError) -> JSONResponse:
    return problem_response(422, "VALIDATION", "Text contains invalid characters")


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # The real error is not sent to the client.
    return problem_response(500, "UNAVAILABLE", "Internal server error")
