"""Secrets and logging (spec 4.5): no URL, plot id, body or exception message in a log record,
the log line of a failed attempt, the httpx loggers, clean exception chains, and the settings repr."""

import logging
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Settings
from fakes import FakeSleep, Script, json_response
from main import create_app
from planner import build_plan
from upstream import Upstream, UpstreamFailure

pytestmark = pytest.mark.anyio

URL_MARK = "URLMARK5521"
PLOT_MARK = "PLOTMARK7731"
BODY_MARK = "BODYMARK3318"
EXC_MARK = "EXCMARK9042"
MARKS = (URL_MARK, PLOT_MARK, BODY_MARK, EXC_MARK)
REGISTRY_URL = f"http://registry.test/{URL_MARK}"
WEATHER_URL = f"http://weather.test/{URL_MARK}"
QUIET = ("httpx", "httpcore", "uvicorn.access")


@pytest.fixture
def all_loggers_at_debug() -> Iterator[None]:
    """Every logger that exists, and the root, at DEBUG; restored afterwards."""
    loggers = [logging.getLogger()] + [
        logger for logger in logging.root.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    ]
    saved = [(logger, logger.level) for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        for logger, level in saved:
            logger.setLevel(level)


def plot(**changes: object) -> dict:
    body = {
        "crop_id": "tomato", "planting_date": "2026-03-01", "area_m2": 1000, "row_spacing_m": 1.5,
        "emitter_spacing_m": 0.4, "soil_id": "soil-loam", "emitter_id": "emitter-1", "lat": 31.3, "lon": 34.8,
    }
    body.update(changes)
    return body


def forecast(**changes: object) -> dict:
    body = {
        "fetched_at": "2026-11-17T06:12:40Z", "stale": False, "source": "open-meteo",
        "days": [{"date": "2026-11-17", "et0_mm": 3.0, "rain_mm": 0.0}],
    }
    body.update(changes)
    return body


def world(*, plot_out=None, weather_out=None) -> Callable[[httpx.Request], object]:
    """The registry and weather behind one handler; the default answers are good."""
    plot_script = plot_out or Script(lambda request: json_response(plot()))
    weather_script = weather_out or Script(lambda request: json_response(forecast()))
    soil = Script(lambda request: json_response({"available_water_mm_per_m": 175}))
    emitter = Script(lambda request: json_response({"flow_lph": 1.0}))

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "weather.test":
            return await weather_script(request)
        if "/v1/soils/" in path:
            return await soil(request)
        if "/v1/emitters/" in path:
            return await emitter(request)
        return await plot_script(request)

    return handler


def client_for(handler, **settings: object) -> TestClient:
    config = Settings(_env_file=None, registry_base_url=REGISTRY_URL, weather_base_url=WEATHER_URL, **settings)
    app = create_app(config, transport=httpx.MockTransport(handler), sleep=FakeSleep())
    return TestClient(app, raise_server_exceptions=False)


def boom(message: str = f"{URL_MARK} {EXC_MARK}") -> Script:
    return Script(httpx.ConnectError(message))


# Every way a request can fail, with a marker in the URL, the id, the body or the exception message.
SCENARIOS = {
    "registry-transport": world(plot_out=boom()),
    "registry-timeout": world(plot_out=Script(httpx.ReadTimeout(f"{URL_MARK} {EXC_MARK}"))),
    "registry-500-body": world(plot_out=Script(json_response({"detail": BODY_MARK}, 500))),
    "registry-not-json": world(plot_out=Script(httpx.Response(200, text=BODY_MARK))),
    "registry-invalid-answer": world(plot_out=Script(json_response(plot(area_m2=BODY_MARK)))),
    "registry-unexpected": world(plot_out=Script(RuntimeError(f"{URL_MARK} {EXC_MARK}"))),
    "registry-404-body": world(plot_out=Script(json_response({"detail": BODY_MARK}, 404))),
    "weather-transport": world(weather_out=boom()),
    "weather-500-body": world(weather_out=Script(json_response({"detail": BODY_MARK}, 500))),
    "weather-invalid-answer": world(weather_out=Script(json_response(forecast(source=BODY_MARK)))),
    "weather-unexpected": world(weather_out=Script(RuntimeError(f"{URL_MARK} {EXC_MARK}"))),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_no_log_record_holds_a_url_a_plot_id_a_body_or_an_exception_message(
    name: str, all_loggers_at_debug: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), client_for(SCENARIOS[name], registry_retries=1, weather_retries=1) as client:
        response = client.get(f"/v1/plots/{PLOT_MARK}/plan?days=1")
    assert response.status_code in (404, 500, 503)
    assert caplog.records, "the scenario must log something, or the check below proves nothing"
    for record in caplog.records:
        assert record.exc_info is None, record.name
        text = record.getMessage() + " " + " ".join(str(arg) for arg in (record.args or ()))
        for mark in MARKS:
            assert mark not in text, f"{mark} in a record of {record.name}"
    for mark in MARKS:
        assert mark not in caplog.text
        assert mark not in response.text


def messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_a_failed_attempt_logs_the_service_the_attempt_number_and_the_kind(
    all_loggers_at_debug: None, caplog: pytest.LogCaptureFixture
) -> None:
    handler = world(plot_out=Script(json_response({}, 500)), weather_out=Script(httpx.ReadTimeout("slow")))
    with caplog.at_level(logging.DEBUG), client_for(handler, registry_retries=1) as client:
        client.get(f"/v1/plots/{PLOT_MARK}/plan?days=1")
    lines = messages(caplog)
    assert "registry-service attempt 1 status 500" in lines
    assert "registry-service attempt 2 status 500" in lines
    assert "registry-service unavailable: status 500" in lines


@pytest.mark.parametrize(
    ("script", "kind"),
    [
        (Script(httpx.ReadTimeout("slow")), "timeout"),
        (Script(httpx.ConnectError("down")), "transport"),
        (Script(httpx.Response(200, text="x")), "not_json"),
    ],
    ids=["timeout", "transport", "not_json"],
)
def test_the_weather_attempt_line_names_weather_the_attempt_and_the_kind(
    script: Script, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), client_for(world(weather_out=script), weather_retries=1) as client:
        client.get(f"/v1/plots/{PLOT_MARK}/plan?days=1")
    lines = messages(caplog)
    assert f"weather-service attempt 1 {kind}" in lines
    assert f"weather-service attempt 2 {kind}" in lines
    assert f"weather-service unavailable: {kind}" in lines


def test_an_invalid_answer_logs_the_service_and_the_rule_only(caplog: pytest.LogCaptureFixture) -> None:
    handler = world(weather_out=Script(json_response(forecast(source=BODY_MARK))))
    with caplog.at_level(logging.DEBUG), client_for(handler) as client:
        client.get(f"/v1/plots/{PLOT_MARK}/plan?days=1")
    assert "weather-service unavailable: invalid source not accepted" in messages(caplog)


def test_the_httpx_and_uvicorn_access_loggers_are_at_warning_after_startup(all_loggers_at_debug: None) -> None:
    for name in QUIET:
        assert logging.getLogger(name).level == logging.DEBUG
    with client_for(world()):
        for name in QUIET:
            assert logging.getLogger(name).level == logging.WARNING


def chain(exc: BaseException | None) -> Iterator[BaseException]:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        # Both links are followed: a __cause__ and a __context__ can differ.
        yield from chain(exc.__cause__)
        exc = exc.__context__


def assert_clean(exc: BaseException) -> None:
    for link in chain(exc):
        module = type(link).__module__.split(".")[0]
        assert module not in ("httpx", "httpcore", "anyio", "h11"), f"{type(link)} in the chain"
        assert not isinstance(link, httpx.HTTPError)
        for mark in MARKS:
            assert mark not in str(link)


FAILURES = {
    "transport": Script(httpx.ConnectError(f"{URL_MARK} {EXC_MARK}")),
    "timeout": Script(httpx.ReadTimeout(f"{URL_MARK} {EXC_MARK}")),
    "unexpected": Script(RuntimeError(f"{URL_MARK} {EXC_MARK}")),
    "status": Script(json_response({"detail": BODY_MARK}, 500)),
    "not_json": Script(httpx.Response(200, text=BODY_MARK)),
}


@pytest.mark.parametrize("name", FAILURES)
async def test_an_upstream_failure_has_no_httpx_exception_in_its_chain(name: str) -> None:
    script = FAILURES[name]
    upstream = Upstream("registry-service", REGISTRY_URL, script.client(), 1.0, 1, 0.0, FakeSleep(), False)
    with pytest.raises(UpstreamFailure) as caught:
        await upstream.get_json(f"/v1/plots/{PLOT_MARK}")
    assert_clean(caught.value)


@pytest.mark.parametrize(
    "plot_out",
    [Script(json_response(plot(area_m2=BODY_MARK))), Script(json_response([BODY_MARK]))],
    ids=["bad-field", "not-an-object"],
)
async def test_an_invalid_answer_has_no_exception_of_the_check_in_its_chain(plot_out: Script) -> None:
    transport = httpx.MockTransport(world(plot_out=plot_out))
    registry = Upstream("registry-service", REGISTRY_URL, httpx.AsyncClient(transport=transport), 1.0, 0, 0.0, FakeSleep(), False)
    weather = Upstream("weather-service", WEATHER_URL, httpx.AsyncClient(transport=transport), 1.0, 0, 0.0, FakeSleep(), True)
    with pytest.raises(UpstreamFailure) as caught:
        await build_plan(PLOT_MARK, 1, registry, weather)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert_clean(caught.value)


def test_the_settings_repr_shows_no_url() -> None:
    settings = Settings(_env_file=None, registry_base_url=REGISTRY_URL, weather_base_url=WEATHER_URL)
    for text in (repr(settings), str(settings)):
        assert URL_MARK not in text
        assert "registry.test" not in text
        assert "weather.test" not in text
