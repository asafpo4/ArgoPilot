import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import config
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

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A ConfigError here stops startup. Its message never contains the URL or password.
    app.state.db_target = config.parse_database_url(os.environ.get("DATABASE_URL"))
    yield


app = FastAPI(title="AgroPilot registry-service", version="0.1.0", lifespan=lifespan)
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
