from http import HTTPStatus

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# The code for each HTTP status we return. Any other status raises KeyError,
# so it fails loudly instead of getting a guessed code.
CODE_BY_STATUS = {404: "NOT_FOUND", 405: "VALIDATION", 409: "CONFLICT", 422: "VALIDATION"}


def problem_response(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
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


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
    return problem_response(422, "VALIDATION", details)
