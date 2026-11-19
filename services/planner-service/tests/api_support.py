"""Support for the API tests: fake upstreams behind one MockTransport, and a client with a running app."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from urllib.parse import quote

import httpx
from fastapi.testclient import TestClient

from config import Settings
from fakes import FakeSleep, Script, json_response
from main import create_app

REGISTRY_URL = "http://registry.test"
WEATHER_URL = "http://weather.test"

TITLES = {404: "Not Found", 405: "Method Not Allowed", 422: "Unprocessable Entity", 500: "Internal Server Error", 503: "Service Unavailable"}
PROBLEM_KEYS = {"type", "title", "status", "detail", "code"}

FIRST_DAY = date(2026, 11, 17)
FETCHED_AT = "2026-11-17T06:12:40Z"
# The North block of the seed data and the three days of the spec example (2.2).
ET0 = (3.0, 2.8, 3.4, 3.0, 3.0, 3.0, 3.0)
RAIN = (0.0, 12.0, 0.3, 0.0, 0.0, 0.0, 0.0)


def plan_url(plot_id: str, query: str = "") -> str:
    """The path of the plan route for a plot id, encoded so that the route receives exactly `plot_id`.

    A real server decodes the path once (checked against uvicorn). Starlette's TestClient decodes it
    twice, so the id is encoded twice here. The route sees the plain id either way.
    """
    return f"/v1/plots/{quote(quote(plot_id, safe=''), safe='')}/plan{query}"


def plot_body(**changes: object) -> dict:
    body = {
        "id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
        "crop_id": "tomato",
        "planting_date": "2026-03-01",
        "area_m2": 1000,
        "row_spacing_m": 1.5,
        "emitter_spacing_m": 0.4,
        "soil_id": "soil-loam",
        "emitter_id": "emitter-1",
        "lat": 31.3,
        "lon": 34.8,
    }
    body.update(changes)
    return body


def forecast_body(rows: int, *, first: date = FIRST_DAY, stale: bool = False, **changes: object) -> dict:
    body = {
        "lat": 31.3,
        "lon": 34.8,
        "fetched_at": FETCHED_AT,
        "stale": stale,
        "source": "open-meteo",
        "days": [
            {"date": (first + timedelta(days=i)).isoformat(), "et0_mm": ET0[i], "rain_mm": RAIN[i]}
            for i in range(rows)
        ],
    }
    body.update(changes)
    return body


def default_forecast(request: httpx.Request) -> httpx.Response:
    return json_response(forecast_body(int(request.url.params["days"])))


class FakeWorld:
    """The registry and weather as one httpx transport handler. Each call goes to a Script."""

    def __init__(
        self,
        *,
        plot: Script | None = None,
        soil: Script | None = None,
        emitter: Script | None = None,
        forecast: Script | None = None,
    ) -> None:
        self.plot = plot or Script(lambda request: json_response(plot_body()))
        self.soil = soil or Script(lambda request: json_response({"available_water_mm_per_m": 175}))
        self.emitter = emitter or Script(lambda request: json_response({"flow_lph": 1.0}))
        self.forecast = forecast or Script(default_forecast)
        self.stray: list[str] = []

    @property
    def total_calls(self) -> int:
        return self.plot.calls + self.soil.calls + self.emitter.calls + self.forecast.calls

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "registry.test" and path.startswith("/v1/plots/"):
            return await self.plot(request)
        if host == "registry.test" and path.startswith("/v1/soils/"):
            return await self.soil(request)
        if host == "registry.test" and path.startswith("/v1/emitters/"):
            return await self.emitter(request)
        if host == "weather.test" and path == "/v1/forecast":
            return await self.forecast(request)
        self.stray.append(f"{host}{path}")
        return httpx.Response(599)


@contextmanager
def planner_client(world: FakeWorld, **settings: object) -> Iterator[TestClient]:
    """A client of the real app, with its lifespan running, over the fake upstreams."""
    config = Settings(_env_file=None, registry_base_url=REGISTRY_URL, weather_base_url=WEATHER_URL, **settings)
    app = create_app(config, transport=httpx.MockTransport(world), sleep=FakeSleep())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_problem(response: httpx.Response, status: int, code: str, detail: str | None = None) -> dict:
    assert response.status_code != 200
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["type"] == "about:blank"
    assert body["title"] == TITLES[status]
    assert body["status"] == status
    assert body["code"] == code
    if detail is not None:
        assert body["detail"] == detail
    return body
