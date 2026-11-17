"""The route end to end: contract, validation before any provider call, failures, and /health."""

import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from provider import Failure
from tests.fakes import FakeClock, FakeProvider, good_forecast, provider_body
from tests.test_service_rules import FAIL, NOON, fc
from test_provider import CONTENT_FAILURES, NOW as PROVIDER_NOW, TRANSPORT_AND_BODY_FAILURES, reply

TODAY = date(2026, 11, 17)
QUERY = "/v1/forecast?lat=31.25&lon=34.79&days=3"
CYCLE = [FAIL, FAIL, FAIL]


def settings(**kw) -> Settings:
    return Settings(PROVIDER_BASE_URL="http://localhost:1", **kw)


def running(outcomes, **kw):
    clock = FakeClock(NOON)
    provider = FakeProvider(outcomes)
    app = create_app(settings(**kw), provider=provider, clock=clock)
    return TestClient(app), provider, clock


def test_the_answer_has_exactly_the_agreed_keys_and_the_providers_values() -> None:
    expected = good_forecast(TODAY).rows
    with running([fc(TODAY)])[0] as client:
        response = client.get(QUERY)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"lat", "lon", "source", "fetched_at", "stale", "days"}
    assert (body["lat"], body["lon"], body["source"], body["stale"]) == (31.25, 34.79, "open-meteo", False)
    assert body["fetched_at"] == "2026-11-17T12:00:00Z"
    assert body["days"] == [
        {"date": r.date.isoformat(), "et0_mm": r.et0_mm, "rain_mm": r.rain_mm} for r in expected[:3]
    ]


def test_stale_answers_carry_stale_true_and_their_own_fetched_at() -> None:
    client, _, clock = running([fc(TODAY), *CYCLE], FRESH_FOR_SECONDS=100)
    with client:
        first = client.get(QUERY).json()
        clock.advance(100)
        second = client.get(QUERY)
    assert second.status_code == 200
    assert second.json()["stale"] is True
    assert second.json()["fetched_at"] == first["fetched_at"] == "2026-11-17T12:00:00Z"
    assert second.json()["days"] == first["days"]


def failing_app(handler, **kw):
    clock = FakeClock(PROVIDER_NOW)
    app = create_app(settings(**kw), transport=httpx.MockTransport(handler), clock=clock)
    return TestClient(app), clock


ALL_FAILURES = [(i, h) for i, h, _ in TRANSPORT_AND_BODY_FAILURES] + [
    (i, lambda request, m=m: reply(m())(request)) for i, m, _ in CONTENT_FAILURES
]


@pytest.mark.parametrize("handler", [h for _, h in ALL_FAILURES], ids=[i for i, _ in ALL_FAILURES])
def test_a_failing_provider_never_gives_a_full_list_of_made_up_values(handler) -> None:
    client, _ = failing_app(handler)
    with client:
        response = client.get(QUERY)
    assert response.status_code == 503  # nothing stored, so nothing to serve: never zeros or defaults
    assert response.headers["Retry-After"] == "30"
    assert "days" not in response.json()


def test_a_null_in_the_last_value_after_a_good_answer_gives_the_old_numbers_not_a_zero() -> None:
    good = provider_body(date(2026, 11, 16))
    null_last = provider_body(date(2026, 11, 16))
    null_last["daily"]["precipitation_sum"][6] = None  # type: ignore[index]
    state = {"body": good}
    client, clock = failing_app(
        lambda request: httpx.Response(200, content=json.dumps(state["body"]).encode()),
        FRESH_FOR_SECONDS=100,
    )
    url = "/v1/forecast?lat=31.25&lon=34.79&days=7"
    with client:
        first = client.get(url).json()
        state["body"] = null_last  # the whole answer is refused, the last value is never made a zero
        clock.advance(100)
        second = client.get(url).json()
    assert second["stale"] is True and second["days"] == first["days"]
    assert len(first["days"]) == 7


def test_503_has_retry_after_and_the_fixed_detail() -> None:
    client, _, _ = running(CYCLE, COOLDOWN_SECONDS=30)
    with client:
        response = client.get(QUERY)
        again = client.get(QUERY)
    assert response.status_code == again.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Forecast unavailable"
    assert response.json()["code"] == "UNAVAILABLE"
    assert response.headers["Retry-After"] == "30"
    assert again.headers["Retry-After"] == "30"  # the fake clock has not moved


BAD_QUERIES = [
    "/v1/forecast",
    "/v1/forecast?lon=34.79&days=3",
    "/v1/forecast?lat=31.25&days=3",
    "/v1/forecast?lat=31.25&lon=34.79",
    "/v1/forecast?lat=abc&lon=34.79&days=3",
    "/v1/forecast?lat=91&lon=34.79&days=3",
    "/v1/forecast?lat=31.25&lon=181&days=3",
    "/v1/forecast?lat=31.25&lon=34.79&days=0",
    "/v1/forecast?lat=31.25&lon=34.79&days=8",
    "/v1/forecast?lat=31.25&lon=34.79&days=03",
    "/v1/forecast?lat=31.25&lat=31.5&lon=34.79&days=3",
    "/v1/forecast?lat=1e999&lon=34.79&days=3",
    "/v1/forecast?lat=NaN&lon=34.79&days=3",
]


@pytest.mark.parametrize("url", BAD_QUERIES)
def test_an_invalid_request_is_422_and_the_provider_is_never_called(url: str) -> None:
    client, provider, _ = running([fc(TODAY)])
    with client:
        response = client.get(url)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"
    assert provider.calls == 0


def test_health_makes_no_provider_call_while_failing_and_during_a_cooldown() -> None:
    client, provider, _ = running(CYCLE, COOLDOWN_SECONDS=30)
    with client:
        assert client.get("/health").json() == {"status": "ok"}
        assert provider.calls == 0
        client.get(QUERY)  # the cycle fails: three calls, the cell is cooling
        assert provider.calls == 3
        assert client.get("/health").status_code == 200
    assert provider.calls == 3
