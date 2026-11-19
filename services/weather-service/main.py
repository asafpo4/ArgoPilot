"""The weather-service HTTP app. Run with: uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from clock import Clock, SystemClock
from config import Settings, load_settings
from errors import ForecastUnavailable, install_handlers
from forecast_service import ForecastService
from grid import cell_for
from provider import OpenMeteoProvider, Provider, silence_http_logs
from schemas import DayOut, ForecastOut, parse_forecast_query


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    provider: Provider | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Build the app. Settings are loaded at startup when not given: a ConfigError stops the start."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else load_settings()  # A ConfigError is not caught.
        the_clock = clock if clock is not None else SystemClock()
        silence_http_logs()  # A request URL, and the key in it, must never reach a log.
        client: httpx.AsyncClient | None = None
        if provider is None:
            client = httpx.AsyncClient(transport=transport)
            the_provider: Provider = OpenMeteoProvider(
                client,
                base_url=config.PROVIDER_BASE_URL,
                api_key=config.api_key(),
                timeout=config.PROVIDER_TIMEOUT_SECONDS,
                clock=the_clock,
            )
        else:
            the_provider = provider
        service = ForecastService(the_provider, the_clock, config)
        app.state.service = service
        try:
            yield
        finally:
            await service.aclose()
            if client is not None:
                await client.aclose()

    app = FastAPI(title="AgroPilot weather-service", version="0.1.0", lifespan=lifespan)
    install_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Never calls the provider and never reads the cache.
        return {"status": "ok"}

    @app.get("/v1/forecast", response_model=ForecastOut)
    async def forecast(request: Request) -> ForecastOut:
        # The raw pairs go to the parser, so a repeated parameter is seen. Nothing is fetched before this passes.
        query = parse_forecast_query(request.query_params.multi_items())
        service: ForecastService = request.app.state.service
        result = await service.get(cell_for(query.lat, query.lon), query.days)
        if result.kind == "unavailable":
            raise ForecastUnavailable(result.retry_after or 1)
        assert result.fetched_at is not None
        return ForecastOut(
            lat=float(query.lat),
            lon=float(query.lon),
            fetched_at=result.fetched_at,
            stale=result.kind == "stale",
            days=[DayOut(date=row.date, et0_mm=row.et0_mm, rain_mm=row.rain_mm) for row in result.rows],
        )

    return app


app = create_app()
