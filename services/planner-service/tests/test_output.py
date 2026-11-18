"""The plan JSON and the rounding (spec 2.2 and 3.7)."""

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from engine import PlotInput, WeatherRow, plan
from output import round_half_up, to_plan_json
from upstream import Forecast, PlotData

TOP_KEYS = {
    "plot_id", "crop_id", "area_m2", "flow_lph", "taw_mm",
    "assumed_start", "forecast", "warnings", "days",
}
DAY_KEYS = {
    "date", "stage", "stale", "et0_mm", "kc", "etc_mm", "rain_mm", "rain_counted_mm",
    "irrigation_mm", "litres", "run_minutes", "capped", "bucket_mm", "trigger_mm",
}

PLOT_ID = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
FETCHED_AT = "2026-11-17T06:12:40Z"

NORTH = PlotInput(
    crop_id="tomato",
    planting_date=date(2026, 3, 1),
    area_m2=1000.0,
    row_spacing_m=1.5,
    emitter_spacing_m=0.4,
    emitter_flow_lph=1.0,
    soil_mm_per_m=175.0,
)


def plot_data(planting: date = date(2026, 3, 1), area: float = 1000.0) -> PlotData:
    return PlotData(
        crop_id="tomato",
        soil_id="s",
        emitter_id="e",
        planting_date=planting,
        area_m2=area,
        row_spacing_m=1.5,
        emitter_spacing_m=0.4,
        lat=31.0,
        lon=34.0,
    )


def forecast(pairs, stale=False, start=date(2026, 11, 17)) -> Forecast:
    rows = tuple(
        WeatherRow(start + timedelta(days=i), et0, rain) for i, (et0, rain) in enumerate(pairs)
    )
    return Forecast(stale=stale, fetched_at=FETCHED_AT, rows=rows)


def build(pairs, *, stale=False, requested=None, planting=date(2026, 3, 1), area=1000.0):
    fc = forecast(pairs, stale=stale)
    pd_ = plot_data(planting, area)
    inp = replace(NORTH, planting_date=planting, area_m2=area)
    result = plan(inp, fc.rows)
    return to_plan_json(PLOT_ID, pd_, fc, result, requested or len(pairs)), fc, result


NORTH_PAIRS = [(3.0, 0.0), (2.8, 12.0), (3.4, 0.3)]


def test_round_half_up_ties_use_decimal_text():
    assert round_half_up(0.125, 2) == 0.13
    assert round_half_up(2.675, 2) == 2.68
    assert round_half_up(0.5, 0) == 1.0
    assert round_half_up(2.5, 0) == 3.0
    assert round_half_up(0.0, 2) == 0.0


def test_top_level_day_and_warning_key_sets():
    out, _, _ = build(NORTH_PAIRS)
    assert set(out) == TOP_KEYS
    assert all(set(day) == DAY_KEYS for day in out["days"])
    assert set(out["assumed_start"]) == {"rule", "bucket_mm"}
    assert set(out["forecast"]) == {"source", "fetched_at"}

    out, _, _ = build(NORTH_PAIRS, requested=7, planting=date(2025, 1, 1))
    assert {w["code"]: set(w) for w in out["warnings"]} == {
        "planting_date_past_cycle": {"code", "days_past_cycle"},
        "forecast_short": {"code", "days_requested", "days_received"},
    }
    out, _, _ = build(NORTH_PAIRS, planting=date(2026, 11, 20))
    assert set(out["warnings"][0]) == {"code", "days_until_planting"}


def test_north_example_values():
    out, _, _ = build(NORTH_PAIRS)
    assert out["plot_id"] == PLOT_ID
    assert out["crop_id"] == "tomato"
    assert out["area_m2"] == 1000
    assert out["flow_lph"] == 1666.67
    assert out["taw_mm"] == 122.5
    first = out["days"][0]
    assert first["kc"] == 0.8
    assert first["etc_mm"] == 2.4
    assert first["irrigation_mm"] == 2.4
    assert first["litres"] == 2400
    assert first["run_minutes"] == 86
    assert first["bucket_mm"] == 60.76
    assert first["trigger_mm"] == 60.76


def test_kc_has_three_decimals():
    # Development stage, d = 33 of tomato: Kc = 0.6 + 3/40 x 0.55 = 0.64125.
    planting = date(2026, 11, 17) - timedelta(days=33)
    out, _, result = build([(5.0, 0.0)], planting=planting)
    assert result.days[0].kc == pytest.approx(0.64125)
    assert out["days"][0]["kc"] == 0.641


def test_litres_and_minutes_are_ints_from_full_precision():
    out, _, result = build(NORTH_PAIRS)
    for day, raw in zip(out["days"], result.days):
        assert type(day["litres"]) is int
        assert type(day["run_minutes"]) is int
        assert day["litres"] == int(round_half_up(raw.litres, 0))
        assert day["run_minutes"] == int(round_half_up(raw.run_minutes, 0))


def test_litres_come_from_full_precision_not_from_rounded_mm():
    # Irrigation 0.8 x 3.1234 = 2.49872 mm on 1000 m2 is 2498.72 L, so 2499 L.
    # The rounded mm (2.5) would give 2500 L.
    out, _, result = build([(3.1234, 0.0)])
    assert result.days[0].irrigation_mm == pytest.approx(2.49872)
    assert out["days"][0]["irrigation_mm"] == 2.5
    assert out["days"][0]["litres"] == 2499
    assert out["days"][0]["litres"] != round(out["days"][0]["irrigation_mm"] * 1000)


def test_tiny_irrigation_runs_at_least_one_minute():
    # Day 1 starts at the trigger, so its irrigation equals its ETc: 0.001 mm needs ET0 = 0.00125.
    out, _, result = build([(0.00125, 0.0)])
    day = out["days"][0]
    assert result.days[0].irrigation_mm == pytest.approx(0.001)
    assert day["irrigation_mm"] == 0.0
    assert day["litres"] == 1
    assert day["run_minutes"] >= 1


def test_run_minutes_is_zero_only_without_irrigation():
    out, _, result = build(NORTH_PAIRS)
    assert result.days[1].irrigation_mm == 0
    assert out["days"][1]["run_minutes"] == 0
    for day, raw in zip(out["days"], result.days):
        assert (day["run_minutes"] == 0) == (raw.irrigation_mm == 0)


def test_stale_on_every_day_is_the_forecast_value():
    for stale in (True, False):
        out, _, _ = build(NORTH_PAIRS, stale=stale)
        assert [day["stale"] for day in out["days"]] == [stale] * 3


def test_forecast_short_only_when_fewer_rows_than_asked():
    out, _, _ = build(NORTH_PAIRS, requested=3, planting=date(2026, 10, 1))
    assert out["warnings"] == []
    out, _, _ = build(NORTH_PAIRS, requested=7, planting=date(2026, 10, 1))
    assert out["warnings"] == [{"code": "forecast_short", "days_requested": 7, "days_received": 3}]


def test_warning_order_planting_first():
    out, _, _ = build(NORTH_PAIRS, requested=7, planting=date(2026, 11, 20))
    assert [w["code"] for w in out["warnings"]] == ["planting_date_in_future", "forecast_short"]
    assert out["warnings"][0] == {"code": "planting_date_in_future", "days_until_planting": 3}


def test_assumed_start_and_forecast_block():
    out, _, result = build(NORTH_PAIRS)
    assert out["assumed_start"] == {"rule": "at_trigger", "bucket_mm": 60.76}
    assert out["assumed_start"]["bucket_mm"] == round_half_up(result.start_bucket_mm, 2)
    assert out["forecast"] == {"source": "open-meteo", "fetched_at": FETCHED_AT}


def test_et0_and_rain_unchanged():
    pairs = [(3.123456, 0.0), (2.8, 0.3333333), (3.4, 12.0)]
    out, _, _ = build(pairs)
    assert [d["et0_mm"] for d in out["days"]] == [3.123456, 2.8, 3.4]
    assert [d["rain_mm"] for d in out["days"]] == [0.0, 0.3333333, 12.0]
    assert [d["date"] for d in out["days"]] == ["2026-11-17", "2026-11-18", "2026-11-19"]


def test_rounded_numbers_are_plain_json_numbers():
    out, _, _ = build(NORTH_PAIRS)
    text = json.dumps(out)
    assert '"kc": 0.8,' in text
    assert "0.800" not in text
    assert '"litres": 2400,' in text
    assert '"run_minutes": 86,' in text


def test_json_never_holds_infinity_or_nan():
    out, _, _ = build(NORTH_PAIRS)
    json.dumps(out, allow_nan=False)
    # round_half_up on a non-finite value must not hand one to the JSON silently.
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            json.dumps(round_half_up(bad, 2), allow_nan=False)
