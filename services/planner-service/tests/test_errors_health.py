import logging

import httpx
import pytest

from api_support import FakeWorld, assert_problem, plan_url, planner_client
from fakes import Script
from main import create_app

MARKER = "SECRET-MARKER-9917"
PLOT_ID = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
FIXED_500 = "Internal server error"


def test_health_is_ok_and_makes_no_upstream_call_while_both_fail() -> None:
    world = FakeWorld(
        plot=Script(httpx.Response(500)),
        soil=Script(httpx.Response(500)),
        emitter=Script(httpx.Response(500)),
        forecast=Script(httpx.ConnectError("x")),
    )
    with planner_client(world) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert world.total_calls == 0


def test_unknown_route_is_404_not_found() -> None:
    with planner_client(FakeWorld()) as client:
        response = client.get("/no-such-route")
    assert_problem(response, 404, "NOT_FOUND")


@pytest.mark.parametrize("path", ["/health", plan_url(PLOT_ID)])
def test_wrong_method_is_405_with_code_validation(path: str) -> None:
    world = FakeWorld()
    with planner_client(world) as client:
        response = client.post(path)
    assert_problem(response, 405, "VALIDATION")
    assert world.total_calls == 0


def test_problem_json_has_the_registry_shape_for_a_422() -> None:
    with planner_client(FakeWorld()) as client:
        response = client.get(plan_url(PLOT_ID, "?days=0"))
    body = assert_problem(response, 422, "VALIDATION", "days: must be one digit from 1 to 7")
    assert body["type"] == "about:blank"


def test_unknown_crop_is_500_unavailable_with_the_fixed_detail_and_no_retry_after(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plot = Script(lambda request: httpx.Response(200, json={
        "crop_id": MARKER, "planting_date": "2026-03-01", "area_m2": 1000, "row_spacing_m": 1.5,
        "emitter_spacing_m": 0.4, "soil_id": "s", "emitter_id": "e", "lat": 31.3, "lon": 34.8,
    }))
    with caplog.at_level(logging.DEBUG), planner_client(FakeWorld(plot=plot)) as client:
        response = client.get(plan_url(PLOT_ID, "?days=3"))
    assert_problem(response, 500, "UNAVAILABLE", FIXED_500)
    assert "Retry-After" not in response.headers
    assert "days" not in response.json()
    assert MARKER not in response.text
    assert MARKER not in caplog.text


def test_unexpected_exception_is_500_and_its_message_is_in_neither_body_nor_log(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(MARKER)

    monkeypatch.setattr("planner.to_plan_json", boom)
    with caplog.at_level(logging.DEBUG), planner_client(FakeWorld()) as client:
        response = client.get(plan_url(PLOT_ID, "?days=3"))
    assert_problem(response, 500, "UNAVAILABLE", FIXED_500)
    assert "Retry-After" not in response.headers
    assert MARKER not in response.text
    assert MARKER not in caplog.text


def test_create_app_without_settings_does_not_read_them_until_startup() -> None:
    # Importing main builds `app`: that must not need a .env file (a ConfigError belongs to startup).
    assert create_app() is not None
