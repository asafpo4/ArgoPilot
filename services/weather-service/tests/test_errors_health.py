import logging

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from errors import ForecastUnavailable, RequestError
from main import create_app

MARKER = "SECRET-MARKER-task1"


def client_with_test_routes() -> tuple[FastAPI, TestClient]:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(MARKER)

    @app.get("/unavailable")
    def unavailable() -> None:
        raise ForecastUnavailable(7)

    @app.get("/bad-input")
    def bad_input() -> None:
        raise RequestError([("lat", "must be a number")])

    return app, TestClient(app, raise_server_exceptions=False)


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert set(response.json()) == {"type", "title", "status", "detail", "code"}
    assert response.json()["status"] == status
    assert response.json()["code"] == code


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_is_404_not_found() -> None:
    response = TestClient(create_app()).get("/no-such-route")
    assert_problem(response, 404, "NOT_FOUND")


def test_wrong_method_is_405_with_code_validation() -> None:
    response = TestClient(create_app()).post("/health")
    assert_problem(response, 405, "VALIDATION")


def test_unexpected_error_is_500_unavailable_without_retry_after(caplog: pytest.LogCaptureFixture) -> None:
    _, client = client_with_test_routes()
    with caplog.at_level(logging.DEBUG):
        response = client.get("/boom")
    assert_problem(response, 500, "UNAVAILABLE")
    assert response.json()["detail"] == "Internal server error"
    assert "Retry-After" not in response.headers
    assert MARKER not in response.text
    assert MARKER not in caplog.text


def test_unexpected_error_is_not_re_raised_to_the_server() -> None:
    # The default client re-raises errors the app did not handle, as a real server would print them.
    # An unexpected error must stay inside the app: the 500 is the answer, and nothing is re-raised,
    # so no traceback with the secret reaches the server log.
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(MARKER)

    response = TestClient(app).get("/boom")
    assert response.status_code == 500


def test_forecast_unavailable_is_503_with_retry_after() -> None:
    _, client = client_with_test_routes()
    response = client.get("/unavailable")
    assert_problem(response, 503, "UNAVAILABLE")
    assert response.headers["Retry-After"] == "7"
    assert response.json()["detail"] == "Forecast unavailable"


def test_request_error_is_422_validation() -> None:
    _, client = client_with_test_routes()
    response = client.get("/bad-input")
    assert_problem(response, 422, "VALIDATION")
    assert response.json()["title"] == "Unprocessable Entity"
    assert response.json()["detail"] == "lat: must be a number"


@pytest.mark.anyio
async def test_async_tests_run_against_the_app() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok"}
