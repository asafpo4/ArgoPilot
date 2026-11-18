"""The planner-service HTTP app. Run with: uv run uvicorn main:app --host 127.0.0.1 --port 8002"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from clock import real_sleep
from config import Settings, load_settings
from errors import install_handlers
from planner import REGISTRY, WEATHER, build_plan
from request import parse_days, plot_id_is_possible
from upstream import NotFound, Upstream


def silence_http_logs() -> None:
    # httpx logs the URL of every request at INFO, and a URL holds a plot id. The uvicorn access
    # line holds the request path, so the plot id of the plan request, and it is quiet at WARNING.
    for name in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> FastAPI:
    """Build the app. Settings are loaded at startup when not given: a ConfigError stops the start."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else load_settings()  # A ConfigError is not caught.
        silence_http_logs()
        the_sleep = sleep if sleep is not None else real_sleep
        # timeout=None: every attempt has its own hard deadline (spec 4.3), and httpx's default
        # per-phase timeout of 5 s would cut a slower weather call short.
        registry_http = httpx.AsyncClient(transport=transport, timeout=None)
        weather_http = httpx.AsyncClient(transport=transport, timeout=None)
        app.state.registry = Upstream(
            REGISTRY, config.registry_base_url, registry_http, config.registry_timeout_seconds,
            config.registry_retries, config.retry_delay_seconds, the_sleep, retry_4xx=False,
        )
        app.state.weather = Upstream(
            WEATHER, config.weather_base_url, weather_http, config.weather_timeout_seconds,
            config.weather_retries, config.retry_delay_seconds, the_sleep, retry_4xx=True,
        )
        try:
            yield
        finally:
            await registry_http.aclose()
            await weather_http.aclose()

    app = FastAPI(title="AgroPilot planner-service", version="0.1.0", lifespan=lifespan)
    install_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Never calls registry or weather.
        return {"status": "ok"}

    @app.get("/v1/plots/{plot_id}/plan")
    async def plan(plot_id: str, request: Request) -> dict:
        # The raw query goes to the check, so a repeated parameter is seen. Nothing is called before it passes.
        days = parse_days(request.scope["query_string"])
        if not plot_id_is_possible(plot_id):
            raise NotFound()
        return await build_plan(plot_id, days, request.app.state.registry, request.app.state.weather)

    return app


app = create_app()
