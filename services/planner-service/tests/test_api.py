import asyncio
import time
from datetime import timedelta

import httpx
import pytest

from api_support import (
    FETCHED_AT,
    FIRST_DAY,
    FakeWorld,
    assert_problem,
    forecast_body,
    plan_url,
    plot_body,
    planner_client,
)
from fakes import Script, json_response

PLOT_ID = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
REGISTRY_DOWN = "registry-service unavailable"
WEATHER_DOWN = "weather-service unavailable"

SPEC_EXAMPLE = {
    "plot_id": PLOT_ID,
    "crop_id": "tomato",
    "area_m2": 1000,
    "flow_lph": 1666.67,
    "taw_mm": 122.5,
    "assumed_start": {"rule": "at_trigger", "bucket_mm": 60.76},
    "forecast": {"source": "open-meteo", "fetched_at": FETCHED_AT},
    "warnings": [{"code": "planting_date_past_cycle", "days_past_cycle": 116}],
    "days": [
        {"date": "2026-11-17", "stage": "after_cycle", "stale": False, "et0_mm": 3.0, "kc": 0.8, "etc_mm": 2.4,
         "rain_mm": 0.0, "rain_counted_mm": 0.0, "irrigation_mm": 2.4, "litres": 2400, "run_minutes": 86,
         "capped": False, "bucket_mm": 60.76, "trigger_mm": 60.76},
        {"date": "2026-11-18", "stage": "after_cycle", "stale": False, "et0_mm": 2.8, "kc": 0.8, "etc_mm": 2.24,
         "rain_mm": 12.0, "rain_counted_mm": 12.0, "irrigation_mm": 0.0, "litres": 0, "run_minutes": 0,
         "capped": False, "bucket_mm": 70.52, "trigger_mm": 59.98},
        {"date": "2026-11-19", "stage": "after_cycle", "stale": False, "et0_mm": 3.4, "kc": 0.8, "etc_mm": 2.72,
         "rain_mm": 0.3, "rain_counted_mm": 0.0, "irrigation_mm": 0.0, "litres": 0, "run_minutes": 0,
         "capped": False, "bucket_mm": 67.8, "trigger_mm": 62.33},
    ],
}


def get_plan(world: FakeWorld, query: str = "?days=3", plot_id: str = PLOT_ID, **settings: object) -> httpx.Response:
    with planner_client(world, **settings) as client:
        return client.get(plan_url(plot_id, query))


def assert_no_plan(response: httpx.Response) -> None:
    # Every failure is a problem answer: never a 200, and never a plan of any kind.
    assert response.status_code != 200
    assert "days" not in response.json()
    assert "warnings" not in response.json()


# --- successful plans ---


def test_fresh_plan_equals_the_spec_example() -> None:
    world = FakeWorld()
    response = get_plan(world)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "Retry-After" not in response.headers
    assert response.json() == SPEC_EXAMPLE
    assert world.stray == []


def test_each_plan_makes_four_upstream_calls_with_the_plot_coordinates_and_days() -> None:
    world = FakeWorld()
    get_plan(world, "?days=3")
    assert [world.plot.calls, world.soil.calls, world.emitter.calls, world.forecast.calls] == [1, 1, 1, 1]
    query = world.forecast.requests[0].url.params
    assert dict(query) == {"lat": "31.3", "lon": "34.8", "days": "3"}
    assert world.soil.requests[0].url.path == "/v1/soils/soil-loam"
    assert world.emitter.requests[0].url.path == "/v1/emitters/emitter-1"


def test_days_absent_means_seven() -> None:
    world = FakeWorld()
    response = get_plan(world, "")
    assert response.status_code == 200
    assert world.forecast.requests[0].url.params["days"] == "7"
    assert len(response.json()["days"]) == 7


def test_stale_plan_marks_every_day_stale() -> None:
    forecast = Script(lambda request: json_response(forecast_body(3, stale=True)))
    response = get_plan(FakeWorld(forecast=forecast))
    assert response.status_code == 200
    assert [day["stale"] for day in response.json()["days"]] == [True, True, True]
    assert "Retry-After" not in response.headers


def test_short_plan_has_forecast_short_and_is_not_padded() -> None:
    forecast = Script(lambda request: json_response(forecast_body(2)))
    response = get_plan(FakeWorld(forecast=forecast), "?days=5")
    assert response.status_code == 200
    body = response.json()
    assert [day["date"] for day in body["days"]] == ["2026-11-17", "2026-11-18"]
    assert body["warnings"] == [
        {"code": "planting_date_past_cycle", "days_past_cycle": 116},
        {"code": "forecast_short", "days_requested": 5, "days_received": 2},
    ]


def test_plan_before_the_planting_date_crosses_it_with_the_right_stage_per_day() -> None:
    plot = Script(lambda request: json_response(plot_body(planting_date="2026-11-19")))
    forecast = Script(lambda request: json_response(forecast_body(4, first=FIRST_DAY)))
    response = get_plan(FakeWorld(plot=plot, forecast=forecast), "?days=4")
    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == [{"code": "planting_date_in_future", "days_until_planting": 2}]
    assert [day["stage"] for day in body["days"]] == ["initial"] * 4
    assert [day["kc"] for day in body["days"]] == [0.6] * 4


def test_plan_that_starts_on_the_last_cycle_day_has_no_warning_and_then_after_cycle() -> None:
    planting = (FIRST_DAY - timedelta(days=145)).isoformat()  # tomato: the cycle length is 145
    plot = Script(lambda request: json_response(plot_body(planting_date=planting)))
    forecast = Script(lambda request: json_response(forecast_body(2)))
    response = get_plan(FakeWorld(plot=plot, forecast=forecast), "?days=2")
    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == []
    assert [day["stage"] for day in body["days"]] == ["late", "after_cycle"]
    assert [day["kc"] for day in body["days"]] == [0.8, 0.8]


def test_registry_5xx_is_retried_and_a_later_success_gives_a_plan() -> None:
    plot = Script(httpx.Response(500), lambda request: json_response(plot_body()))
    world = FakeWorld(plot=plot)
    response = get_plan(world)
    assert response.status_code == 200
    assert plot.calls == 2


# --- the request and the ids ---


def test_unknown_plot_is_404_and_weather_is_not_called() -> None:
    world = FakeWorld(plot=Script(httpx.Response(404, json={"detail": "x"})))
    response = get_plan(world)
    assert_problem(response, 404, "NOT_FOUND", "Plot not found")
    assert_no_plan(response)
    assert (world.plot.calls, world.soil.calls, world.emitter.calls, world.forecast.calls) == (1, 0, 0, 0)


@pytest.mark.parametrize("plot_id", ["a" * 65, "a\x00b"])
def test_an_id_that_cannot_exist_is_404_without_a_registry_call(plot_id: str) -> None:
    world = FakeWorld()
    response = get_plan(world, plot_id=plot_id)
    assert_problem(response, 404, "NOT_FOUND", "Plot not found")
    assert_no_plan(response)
    assert world.total_calls == 0


def test_an_id_of_64_characters_goes_to_registry() -> None:
    world = FakeWorld()
    get_plan(world, plot_id="a" * 64)
    assert world.plot.calls == 1


@pytest.mark.parametrize(
    "query",
    [
        "?days=0", "?days=8", "?days=9", "?days=10", "?days=07", "?days=%2B3", "?days=-3", "?days=%203",
        "?days=3%20", "?days=3.0", "?days=3.5", "?days=3e0", "?days=%D9%A3", "?days=%EF%BC%93", "?days=",
        "?days=1&days=2", "?days=3%0A",
    ],
)
def test_bad_days_is_422_without_an_upstream_call(query: str) -> None:
    world = FakeWorld()
    response = get_plan(world, query)
    assert_problem(response, 422, "VALIDATION", "days: must be one digit from 1 to 7")
    assert_no_plan(response)
    assert world.total_calls == 0


@pytest.mark.parametrize("query", ["?days=3&other=x", "?other=%FF&days=3"])
def test_other_parameters_are_ignored(query: str) -> None:
    assert get_plan(FakeWorld(), query).status_code == 200


def test_a_plot_id_with_special_characters_reaches_registry_percent_encoded() -> None:
    world = FakeWorld()
    # The route receives the text a%2Fb c é; registry must receive it encoded: % becomes %25.
    response = get_plan(world, plot_id="a%2Fb c é")
    assert response.status_code == 200
    assert response.json()["plot_id"] == "a%2Fb c é"
    assert world.plot.requests[0].url.raw_path == b"/v1/plots/a%252Fb%20c%20%C3%A9"


def test_soil_and_emitter_ids_from_registry_are_percent_encoded_too() -> None:
    plot = Script(lambda request: json_response(plot_body(soil_id="so/il ../x", emitter_id="e?m#1")))
    world = FakeWorld(plot=plot)
    assert get_plan(world).status_code == 200
    assert world.soil.requests[0].url.raw_path == b"/v1/soils/so%2Fil%20..%2Fx"
    assert world.emitter.requests[0].url.raw_path == b"/v1/emitters/e%3Fm%231"


# --- registry failures ---

REGISTRY_FAILURES = {
    "plot 500": dict(plot=Script(httpx.Response(500, headers={"Retry-After": "9"}))),
    "plot 400": dict(plot=Script(httpx.Response(400))),
    "plot transport": dict(plot=Script(httpx.ConnectError("x"))),
    "plot timeout": dict(plot=Script(httpx.ReadTimeout("x"))),
    "plot not json": dict(plot=Script(httpx.Response(200, content=b"<html>"))),
    "plot not an object": dict(plot=Script(json_response([1, 2]))),
    "plot missing field": dict(plot=Script(json_response({"crop_id": "tomato"}))),
    "plot zero area": dict(plot=Script(lambda request: json_response(plot_body(area_m2=0)))),
    "plot redirect": dict(plot=Script(httpx.Response(302, headers={"Location": "http://elsewhere.test/"}))),
    "soil 404": dict(soil=Script(httpx.Response(404))),
    "soil 500": dict(soil=Script(httpx.Response(500))),
    "soil invalid": dict(soil=Script(json_response({"available_water_mm_per_m": "175"}))),
    "emitter 404": dict(emitter=Script(httpx.Response(404))),
    "emitter 500": dict(emitter=Script(httpx.Response(500))),
    "emitter invalid": dict(emitter=Script(json_response({"flow_lph": True}))),
}


@pytest.mark.parametrize("name", list(REGISTRY_FAILURES))
def test_registry_failure_is_503_naming_registry(name: str) -> None:
    # The scripts are shared by the parametrization, so each test works on a fresh copy of the world.
    changes = {key: Script(*script._outcomes) for key, script in REGISTRY_FAILURES[name].items()}
    world = FakeWorld(**changes)
    response = get_plan(world)
    assert_problem(response, 503, "UPSTREAM_UNAVAILABLE", REGISTRY_DOWN)
    assert_no_plan(response)
    assert response.headers["Retry-After"].isdigit()
    if name.startswith("plot"):
        assert world.soil.calls == world.emitter.calls == world.forecast.calls == 0


def test_registry_retry_after_is_taken_from_the_failing_answer() -> None:
    plot = Script(httpx.Response(500, headers={"Retry-After": "9"}))
    response = get_plan(FakeWorld(plot=plot))
    assert response.headers["Retry-After"] == "9"


# --- weather failures ---

WEATHER_FAILURES = {
    "500": Script(httpx.Response(500)),
    "503": Script(httpx.Response(503, headers={"Retry-After": "7"})),
    "404": Script(httpx.Response(404)),
    "transport": Script(httpx.ConnectError("x")),
    "timeout": Script(httpx.ReadTimeout("x")),
    "not json": Script(httpx.Response(200, content=b"<html>")),
    "redirect": Script(httpx.Response(302, headers={"Location": "http://elsewhere.test/"})),
    "stale not a boolean": Script(lambda request: json_response(forecast_body(3, stale="no"))),
    "stale missing": Script(lambda request: json_response({k: v for k, v in forecast_body(3).items() if k != "stale"})),
    "source": Script(lambda request: json_response(forecast_body(3, source="other"))),
    "empty days": Script(lambda request: json_response(forecast_body(0))),
    "too many days": Script(lambda request: json_response(forecast_body(5))),
    "negative rain": Script(
        lambda request: json_response({**forecast_body(3), "days": [{"date": "2026-11-17", "et0_mm": 3, "rain_mm": -1}]})
    ),
}


@pytest.mark.parametrize("name", list(WEATHER_FAILURES))
def test_weather_failure_is_503_naming_weather(name: str) -> None:
    world = FakeWorld(forecast=Script(*WEATHER_FAILURES[name]._outcomes))
    response = get_plan(world)
    assert_problem(response, 503, "UPSTREAM_UNAVAILABLE", WEATHER_DOWN)
    assert_no_plan(response)
    assert response.headers["Retry-After"].isdigit()


def test_weather_date_gap_is_503_naming_weather() -> None:
    def gap(request: httpx.Request) -> httpx.Response:
        body = forecast_body(3)
        body["days"][2]["date"] = "2026-11-20"
        return json_response(body)

    response = get_plan(FakeWorld(forecast=Script(gap)))
    assert_problem(response, 503, "UPSTREAM_UNAVAILABLE", WEATHER_DOWN)
    assert_no_plan(response)


def test_weather_retry_after_is_taken_from_the_answer_or_is_5() -> None:
    kept = get_plan(FakeWorld(forecast=Script(httpx.Response(503, headers={"Retry-After": "7"}))))
    assert kept.headers["Retry-After"] == "7"
    for header in ({}, {"Retry-After": "0"}, {"Retry-After": "61"}, {"Retry-After": "soon"}):
        response = get_plan(FakeWorld(forecast=Script(httpx.Response(503, headers=header))))
        assert response.headers["Retry-After"] == "5"


def test_a_failed_call_does_not_become_a_plan_of_zeros() -> None:
    # The three calls of the parallel step each fail in turn: the answer is a 503 and no day appears.
    for changes in (
        dict(soil=Script(httpx.Response(500))),
        dict(emitter=Script(httpx.Response(500))),
        dict(forecast=Script(httpx.Response(500))),
    ):
        response = get_plan(FakeWorld(**changes))
        assert response.status_code == 503
        assert_no_plan(response)


# --- the first failure wins ---


def test_first_failure_wins_and_the_sibling_calls_are_cancelled() -> None:
    state = {"started": asyncio.Event(), "cancelled": False}

    async def never_answers(request: httpx.Request) -> httpx.Response:
        state["started"].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        raise AssertionError("unreachable")

    async def soil_fails_once_weather_has_started(request: httpx.Request) -> httpx.Response:
        await state["started"].wait()
        return httpx.Response(404)

    world = FakeWorld(forecast=Script(never_answers), soil=Script(soil_fails_once_weather_has_started))
    began = time.monotonic()
    # Weather would wait for its whole deadline (30 s) if nothing cancelled it. Registry's own deadline
    # is short, so a plan that runs the calls one after the other fails this test instead of hanging it.
    response = get_plan(world, weather_timeout_seconds=30, registry_timeout_seconds=1, registry_retries=0)
    elapsed = time.monotonic() - began
    assert_problem(response, 503, "UPSTREAM_UNAVAILABLE", REGISTRY_DOWN)
    assert state["cancelled"] is True
    assert elapsed < 0.9
    assert world.forecast.calls == 1
