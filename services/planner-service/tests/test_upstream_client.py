import asyncio
import logging
import re
import time

import httpx
import pytest

from clock import real_sleep
from fakes import FakeSleep, Script, block_forever, json_response
from upstream import NotFound, Upstream, UpstreamFailure, forecast_query

pytestmark = pytest.mark.anyio

MARKER = "SECRET-MARKER-8431"
BODY = {"ok": True}
# The coordinate form that weather accepts (copied as text, never imported).
WEATHER_COORDINATE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?")


def make(script, *, service="registry-service", timeout=1.0, retries=1, delay=0.3, retry_4xx=False, sleep=None):
    sleep = sleep or FakeSleep()
    upstream = Upstream(
        service, "http://upstream.test", script.client(), timeout, retries, delay, sleep, retry_4xx
    )
    return upstream, sleep


async def failure_of(upstream, *args, **kwargs) -> UpstreamFailure:
    with pytest.raises(UpstreamFailure) as caught:
        await upstream.get_json(*args, **kwargs)
    return caught.value


def chain(exc: BaseException | None):
    while exc is not None:
        yield exc
        exc = exc.__cause__ or exc.__context__


# ---- registry style: retry_4xx=False ----


@pytest.mark.parametrize(
    "first",
    [
        json_response({}, 500),
        json_response({}, 503),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
    ],
    ids=["500", "503", "httpx-timeout", "transport"],
)
async def test_registry_retries_and_a_later_success_returns_the_body(first):
    script = Script(first, json_response(BODY))
    upstream, sleep = make(script)
    assert await upstream.get_json("/v1/plots/p1") == BODY
    assert script.calls == 2
    assert sleep.delays == [0.3]


async def test_registry_retries_a_hanging_attempt():
    calls = []

    async def first_hangs_then_answers(request):
        calls.append(request)
        if len(calls) == 1:
            await asyncio.Event().wait()
        return json_response(BODY)

    script = Script(first_hangs_then_answers)
    upstream, sleep = make(script, timeout=0.05)
    assert await upstream.get_json("/x") == BODY
    assert len(calls) == 2


async def test_registry_all_attempts_fail_and_the_delay_is_not_slept_after_the_last():
    script = Script(json_response({}, 500))
    upstream, sleep = make(script, retries=1)
    failure = await failure_of(upstream, "/x")
    assert (failure.service, failure.kind) == ("registry-service", "status 500")
    assert script.calls == 2
    assert sleep.delays == [0.3]


async def test_not_found_with_not_found_ok_is_raised_and_not_retried():
    script = Script(json_response({}, 404))
    upstream, sleep = make(script)
    with pytest.raises(NotFound):
        await upstream.get_json("/v1/plots/p1", not_found_ok=True)
    assert script.calls == 1
    assert sleep.delays == []


async def test_not_found_without_not_found_ok_is_a_failure_and_not_retried():
    script = Script(json_response({}, 404))
    upstream, sleep = make(script)
    failure = await failure_of(upstream, "/v1/soils/s1")
    assert failure.kind == "status 404"
    assert script.calls == 1
    assert sleep.delays == []


@pytest.mark.parametrize("status", [400, 401, 403, 409, 422, 429])
async def test_other_4xx_is_not_retried_in_the_registry_style(status):
    script = Script(json_response({}, status))
    upstream, sleep = make(script)
    failure = await failure_of(upstream, "/x")
    assert failure.kind == f"status {status}"
    assert script.calls == 1
    assert sleep.delays == []


async def test_not_json_is_not_retried_in_the_registry_style():
    script = Script(httpx.Response(200, content=b"<html>not json</html>"))
    upstream, sleep = make(script)
    failure = await failure_of(upstream, "/x")
    assert failure.kind == "not_json"
    assert script.calls == 1


async def test_redirects_are_failures_and_are_not_followed():
    redirect = httpx.Response(302, headers={"Location": "http://elsewhere.test/x"})
    script = Script(redirect, json_response(BODY))
    upstream, sleep = make(script)
    failure = await failure_of(upstream, "/x")
    assert failure.kind == "status 302"
    assert script.calls == 1


async def test_a_success_status_other_than_200_is_a_failure():
    script = Script(httpx.Response(204))
    upstream, _ = make(script)
    assert (await failure_of(upstream, "/x")).kind == "status 204"


async def test_params_are_sent_and_the_body_is_returned():
    script = Script(json_response(BODY))
    upstream, _ = make(script, service="weather-service")
    await upstream.get_json("/v1/forecast", {"lat": "31", "lon": "1e-05", "days": "3"})
    request = script.requests[0]
    assert request.url.path == "/v1/forecast"
    assert dict(request.url.params) == {"lat": "31", "lon": "1e-05", "days": "3"}


# ---- weather style: every failure is retried, up to `retries` ----


@pytest.mark.parametrize(
    "outcome",
    [
        json_response({}, 500),
        json_response({}, 404),
        json_response({}, 400),
        httpx.Response(200, content=b"nope"),
        httpx.ConnectError("down"),
    ],
)
async def test_weather_with_no_retries_fails_at_once(outcome):
    script = Script(outcome)
    upstream, sleep = make(script, service="weather-service", retries=0, retry_4xx=True)
    failure = await failure_of(upstream, "/x")
    assert failure.service == "weather-service"
    assert script.calls == 1
    assert sleep.delays == []


@pytest.mark.parametrize(
    "outcome",
    [
        json_response({}, 500),
        json_response({}, 404),
        json_response({}, 400),
        httpx.Response(200, content=b"nope"),
        httpx.ConnectError("down"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_weather_with_two_retries_retries_every_failure(outcome):
    script = Script(outcome)
    upstream, sleep = make(script, service="weather-service", retries=2, delay=0.5, retry_4xx=True)
    await failure_of(upstream, "/x")
    assert script.calls == 3
    assert sleep.delays == [0.5, 0.5]


async def test_weather_retry_can_end_in_success():
    script = Script(json_response({}, 404), json_response(BODY))
    upstream, sleep = make(script, service="weather-service", retries=2, retry_4xx=True)
    assert await upstream.get_json("/x") == BODY
    assert script.calls == 2
    assert sleep.delays == [0.3]


# ---- failure kinds ----


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.PoolTimeout("full"), "timeout"),
        (httpx.ConnectError("down"), "transport"),
        (httpx.RemoteProtocolError("bad"), "transport"),
        (json_response({}, 502), "status 502"),
        (httpx.Response(200, content=b"{"), "not_json"),
    ],
)
async def test_failure_kinds(outcome, kind):
    upstream, _ = make(Script(outcome), retries=0)
    assert (await failure_of(upstream, "/x")).kind == kind


# ---- Retry-After ----


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", 7), ("1", 1), ("60", 60), ("0", 5), ("61", 5), ("abc", 5), ("-3", 5), ("7.5", 5), ("", 5), (None, 5)],
)
async def test_retry_after_of_the_failing_answer(header, expected):
    headers = {} if header is None else {"Retry-After": header}
    upstream, _ = make(Script(json_response({}, 503, headers)), retries=0)
    assert (await failure_of(upstream, "/x")).retry_after == expected


async def test_retry_after_is_5_when_there_was_no_answer():
    upstream, _ = make(Script(httpx.ConnectError("down")), retries=0)
    assert (await failure_of(upstream, "/x")).retry_after == 5


async def test_retry_after_comes_from_the_last_attempt():
    script = Script(json_response({}, 503, {"Retry-After": "9"}), json_response({}, 503, {"Retry-After": "7"}))
    upstream, _ = make(script, retries=1)
    assert (await failure_of(upstream, "/x")).retry_after == 7


# ---- the hard deadline ----


async def test_a_blocking_client_fails_each_attempt_inside_the_deadline():
    calls = []

    async def counting_block(request):
        calls.append(request)
        return await block_forever(request)

    upstream, _ = make(Script(counting_block), timeout=0.05, retries=0)
    started = time.monotonic()
    failure = await failure_of(upstream, "/x")
    assert failure.kind == "timeout"
    assert time.monotonic() - started < 0.05 + 0.25
    assert len(calls) == 1


async def test_a_whole_cycle_ends_within_the_worst_case():
    timeout, retries, delay = 0.05, 2, 0.02
    script = Script(block_forever)
    upstream, _ = make(script, timeout=timeout, retries=retries, delay=delay, sleep=real_sleep)
    started = time.monotonic()
    failure = await failure_of(upstream, "/x")
    elapsed = time.monotonic() - started
    assert failure.kind == "timeout"
    assert script.calls == retries + 1
    assert elapsed >= (retries + 1) * timeout
    assert elapsed < (retries + 1) * timeout + retries * delay + 0.25


# ---- forecast_query ----


def test_forecast_query_uses_the_shortest_decimal_text():
    query = forecast_query(31, 1e-05, 3)
    assert query == {"lat": "31", "lon": "1e-05", "days": "3"}
    for key in ("lat", "lon"):
        assert WEATHER_COORDINATE.fullmatch(query[key])


@pytest.mark.parametrize("value", [31.25, -90, 180.0, 34.79, 1e-05, -1e-07, 0, 0.1])
def test_forecast_query_text_matches_the_weather_pattern(value):
    query = forecast_query(value, value, 7)
    assert WEATHER_COORDINATE.fullmatch(query["lat"])
    assert float(query["lon"]) == value


# ---- logging and secrets ----


@pytest.fixture(autouse=True)
def quiet_httpx():
    # main.py sets these two loggers to WARNING at startup (task 9); the tests do the same here.
    saved = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    for name in saved:
        logging.getLogger(name).setLevel(logging.WARNING)
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


async def test_the_log_has_service_attempt_and_kind_and_nothing_else(caplog):
    script = Script(json_response({}, 503), httpx.ReadTimeout(MARKER), httpx.Response(200, content=MARKER.encode()))
    upstream, _ = make(script, service="weather-service", retries=2, retry_4xx=True)
    with caplog.at_level(logging.DEBUG):
        await failure_of(upstream, f"/v1/plots/{MARKER}", {"q": MARKER})
    records = [r for r in caplog.records if r.name == "upstream"]
    assert [r.getMessage() for r in records] == [
        "weather-service attempt 1 status 503",
        "weather-service attempt 2 timeout",
        "weather-service attempt 3 not_json",
    ]
    assert all(r.levelno == logging.WARNING and r.exc_info is None for r in records)
    assert MARKER not in caplog.text


async def test_an_unexpected_exception_is_logged_by_class_only_and_counts_as_a_failed_attempt(caplog):
    script = Script(RuntimeError(MARKER), json_response(BODY))
    upstream, sleep = make(script, retries=1)
    with caplog.at_level(logging.DEBUG):
        assert await upstream.get_json(f"/{MARKER}", {"q": MARKER}) == BODY
    assert script.calls == 2
    assert sleep.delays == [0.3]
    assert MARKER not in caplog.text
    assert "RuntimeError" in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


async def test_an_unexpected_exception_that_keeps_failing_ends_as_a_failure(caplog):
    upstream, _ = make(Script(RuntimeError(MARKER)), retries=1)
    with caplog.at_level(logging.DEBUG):
        failure = await failure_of(upstream, "/x")
    assert failure.service == "registry-service"
    assert failure.kind == "transport"
    assert MARKER not in caplog.text


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ReadTimeout(MARKER),
        httpx.ConnectError(MARKER),
        RuntimeError(MARKER),
        httpx.Response(200, content=MARKER.encode()),
        httpx.Response(200, content=b'{"a": "' + MARKER.encode()),
        httpx.Response(500, content=MARKER.encode()),
    ],
)
async def test_no_secret_in_the_error_its_repr_or_its_chain(outcome):
    upstream, _ = make(Script(outcome), retries=0)
    failure = await failure_of(upstream, f"/v1/plots/{MARKER}", {"q": MARKER})
    for text in (str(failure), repr(failure), f"{failure.args}"):
        assert MARKER not in text
        assert "upstream.test" not in text
    assert failure.__cause__ is None
    assert failure.__context__ is None
    assert not [e for e in chain(failure) if e is not failure]


async def test_not_found_carries_nothing():
    upstream, _ = make(Script(json_response({}, 404)))
    with pytest.raises(NotFound) as caught:
        await upstream.get_json(f"/v1/plots/{MARKER}", not_found_ok=True)
    assert MARKER not in str(caught.value) + repr(caught.value)
    assert caught.value.__context__ is None
