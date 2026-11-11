from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from catalogues import router as catalogues_router
from db import DatabaseUnavailable
from errors import (
    database_unavailable_handler,
    http_exception_handler,
    invalid_text_handler,
    unexpected_error_handler,
    validation_exception_handler,
)
from farms import router as farms_router
from plots import router as plots_router

app = FastAPI(title="AgroPilot registry-service", version="0.1.0")
app.include_router(catalogues_router)
app.include_router(farms_router)
app.include_router(plots_router)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(DatabaseUnavailable, database_unavailable_handler)
app.add_exception_handler(UnicodeEncodeError, invalid_text_handler)
app.add_exception_handler(Exception, unexpected_error_handler)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
