import copy
import math
from datetime import date

import pytest

from engine import WeatherRow
from upstream import (
    Forecast,
    InvalidAnswer,
    PlotData,
    parse_emitter,
    parse_forecast,
    parse_plot,
    parse_soil,
)

PLOT = {
    "crop_id": "tomato",
    "soil_id": "loam",
    "emitter_id": "drip-2",
    "planting_date": "2026-10-01",
    "area_m2": 100.0,
    "row_spacing_m": 1.5,
    "emitter_spacing_m": 0.4,
    "lat": 31.5,
    "lon": 34.8,
}

FORECAST = {
    "stale": False,
    "source": "open-meteo",
    "fetched_at": "2026-11-18T06:00:00Z",
    "days": [
        {"date": "2026-11-18", "et0_mm": 3.5, "rain_mm": 0.0},
        {"date": "2026-11-19", "et0_mm": 4.0, "rain_mm": 1.2},
        {"date": "2026-11-20", "et0_mm": 0, "rain_mm": 0},
    ],
}


def plot_with(**changes):
    body = copy.deepcopy(PLOT)
    body.update(changes)
    return body


def plot_without(key):
    body = copy.deepcopy(PLOT)
    del body[key]
    return body


def forecast_with(**changes):
    body = copy.deepcopy(FORECAST)
    body.update(changes)
    return body


def forecast_days(days):
    return forecast_with(days=days)


def row(day, et0=3.0, rain=0.0):
    return {"date": f"2026-11-{day:02d}", "et0_mm": et0, "rain_mm": rain}


def assert_invalid(call, *args):
    with pytest.raises(InvalidAnswer) as caught:
        call(*args)
    assert isinstance(caught.value.rule, str) and caught.value.rule
    return caught.value


# ---- valid bodies ----


def test_valid_plot():
    plot = parse_plot(PLOT)
    assert plot == PlotData(
        crop_id="tomato",
        soil_id="loam",
        emitter_id="drip-2",
        planting_date=date(2026, 10, 1),
        area_m2=100.0,
        row_spacing_m=1.5,
        emitter_spacing_m=0.4,
        lat=31.5,
        lon=34.8,
    )


def test_plot_accepts_integers_and_extra_fields():
    plot = parse_plot(plot_with(area_m2=100, lat=31, lon=-34, extra="ignored"))
    assert plot.area_m2 == 100
    assert plot.lat == 31


@pytest.mark.parametrize("lat, lon", [(90, 180), (-90, -180), (0, 0)])
def test_plot_coordinate_limits_are_inclusive(lat, lon):
    plot = parse_plot(plot_with(lat=lat, lon=lon))
    assert (plot.lat, plot.lon) == (lat, lon)


def test_valid_soil_and_emitter():
    assert parse_soil({"available_water_mm_per_m": 140.0}) == 140.0
    assert parse_soil({"available_water_mm_per_m": 140, "x": 1}) == 140
    assert parse_emitter({"flow_lph": 2.0}) == 2.0
    assert parse_emitter({"flow_lph": 2}) == 2


def test_valid_forecast():
    forecast = parse_forecast(FORECAST, 3)
    assert forecast == Forecast(
        stale=False,
        fetched_at="2026-11-18T06:00:00Z",
        rows=(
            WeatherRow(date(2026, 11, 18), 3.5, 0.0),
            WeatherRow(date(2026, 11, 19), 4.0, 1.2),
            WeatherRow(date(2026, 11, 20), 0, 0),
        ),
    )
    assert isinstance(forecast.rows, tuple)


def test_forecast_stale_true_is_valid():
    assert parse_forecast(forecast_with(stale=True), 3).stale is True


def test_fewer_rows_than_asked_is_valid():
    forecast = parse_forecast(forecast_days([row(18), row(19)]), 7)
    assert len(forecast.rows) == 2


def test_one_row_is_valid():
    assert len(parse_forecast(forecast_days([row(18)]), 1).rows) == 1


def test_forecast_dates_may_cross_a_month_boundary():
    days = [
        {"date": "2026-11-30", "et0_mm": 1, "rain_mm": 0},
        {"date": "2026-12-01", "et0_mm": 1, "rain_mm": 0},
    ]
    assert len(parse_forecast(forecast_days(days), 2).rows) == 2


def test_forecast_ignores_extra_fields():
    body = forecast_with(extra=1)
    body["days"][0]["extra"] = "x"
    assert len(parse_forecast(body, 3).rows) == 3


# ---- plot failures ----

NOT_OBJECTS = [None, [], "text", 5, True, 1.5]


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_plot_not_an_object(body):
    assert_invalid(parse_plot, body)


@pytest.mark.parametrize("key", list(PLOT))
def test_plot_missing_field(key):
    assert_invalid(parse_plot, plot_without(key))


@pytest.mark.parametrize("key", list(PLOT))
def test_plot_null_field(key):
    assert_invalid(parse_plot, plot_with(**{key: None}))


@pytest.mark.parametrize("key", ["crop_id", "soil_id", "emitter_id"])
@pytest.mark.parametrize("value", ["", 5, True, ["a"]])
def test_plot_bad_ids(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize(
    "value",
    ["2026-13-01", "2026-02-30", "26-10-01", "2026/10/01", "20261001", "", "x", 20261001, True],
)
def test_plot_bad_planting_date(value):
    assert_invalid(parse_plot, plot_with(planting_date=value))


POSITIVE_KEYS = ["area_m2", "row_spacing_m", "emitter_spacing_m"]
NOT_NUMBERS = ["1.5", "", True, False, [1], {"a": 1}]
NOT_FINITE = [math.nan, math.inf, -math.inf]


@pytest.mark.parametrize("key", POSITIVE_KEYS)
@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_plot_positive_field_not_a_number(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize("key", POSITIVE_KEYS)
@pytest.mark.parametrize("value", NOT_FINITE)
def test_plot_positive_field_not_finite(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize("key", POSITIVE_KEYS)
@pytest.mark.parametrize("value", [0, 0.0, -1, -0.5])
def test_plot_positive_field_zero_or_negative(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize("key", ["lat", "lon"])
@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_plot_coordinate_not_a_number(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize("key", ["lat", "lon"])
@pytest.mark.parametrize("value", NOT_FINITE)
def test_plot_coordinate_not_finite(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


@pytest.mark.parametrize(
    "key, value", [("lat", 91), ("lat", -90.01), ("lon", -181), ("lon", 180.5)]
)
def test_plot_coordinate_out_of_range(key, value):
    assert_invalid(parse_plot, plot_with(**{key: value}))


# ---- soil and emitter failures ----

SOIL_BAD = [
    None,
    [],
    "x",
    True,
    {},
    {"available_water_mm_per_m": None},
    {"available_water_mm_per_m": "140"},
    {"available_water_mm_per_m": True},
    {"available_water_mm_per_m": math.nan},
    {"available_water_mm_per_m": math.inf},
    {"available_water_mm_per_m": 0},
    {"available_water_mm_per_m": -5},
]


@pytest.mark.parametrize("body", SOIL_BAD)
def test_soil_failures(body):
    assert_invalid(parse_soil, body)


EMITTER_BAD = [
    None,
    [],
    "x",
    True,
    {},
    {"flow_lph": None},
    {"flow_lph": "2"},
    {"flow_lph": True},
    {"flow_lph": math.nan},
    {"flow_lph": -math.inf},
    {"flow_lph": 0},
    {"flow_lph": -2.0},
]


@pytest.mark.parametrize("body", EMITTER_BAD)
def test_emitter_failures(body):
    assert_invalid(parse_emitter, body)


# ---- forecast failures ----


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_forecast_not_an_object(body):
    assert_invalid(parse_forecast, body, 3)


@pytest.mark.parametrize("key", ["stale", "source", "fetched_at", "days"])
def test_forecast_missing_field(key):
    body = copy.deepcopy(FORECAST)
    del body[key]
    assert_invalid(parse_forecast, body, 3)


@pytest.mark.parametrize("key", ["stale", "source", "fetched_at", "days"])
def test_forecast_null_field(key):
    assert_invalid(parse_forecast, forecast_with(**{key: None}), 3)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, "", []])
def test_forecast_stale_not_a_boolean(value):
    assert_invalid(parse_forecast, forecast_with(stale=value), 3)


@pytest.mark.parametrize("value", ["open-meteo2", "Open-Meteo", "other", "", 5, True])
def test_forecast_wrong_source(value):
    assert_invalid(parse_forecast, forecast_with(source=value), 3)


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-18T06:00:00",
        "2026-11-18T06:00:00+00:00",
        "2026-11-18 06:00:00Z",
        "2026-11-18Z",
        "2026-13-18T06:00:00Z",
        "2026-11-18T25:00:00Z",
        "yesterday",
        "",
        20261118,
        True,
    ],
)
def test_forecast_bad_fetched_at(value):
    assert_invalid(parse_forecast, forecast_with(fetched_at=value), 3)


@pytest.mark.parametrize("value", ["list", {}, "", 3, True])
def test_forecast_days_not_a_list(value):
    assert_invalid(parse_forecast, forecast_days(value), 3)


def test_forecast_zero_rows():
    assert_invalid(parse_forecast, forecast_days([]), 3)


def test_forecast_more_rows_than_asked():
    days = [row(18), row(19), row(20), row(21)]
    assert_invalid(parse_forecast, forecast_days(days), 3)


def test_forecast_gap_in_dates():
    assert_invalid(parse_forecast, forecast_days([row(18), row(20)]), 3)


def test_forecast_repeated_date():
    assert_invalid(parse_forecast, forecast_days([row(18), row(18)]), 3)


def test_forecast_wrong_order():
    assert_invalid(parse_forecast, forecast_days([row(19), row(18)]), 3)


@pytest.mark.parametrize("item", [None, [], "x", 5, True])
def test_forecast_row_not_an_object(item):
    assert_invalid(parse_forecast, forecast_days([row(18), item]), 3)


@pytest.mark.parametrize("key", ["date", "et0_mm", "rain_mm"])
def test_forecast_row_missing_field(key):
    bad = row(19)
    del bad[key]
    assert_invalid(parse_forecast, forecast_days([row(18), bad]), 3)


@pytest.mark.parametrize("key", ["date", "et0_mm", "rain_mm"])
def test_forecast_row_null_field(key):
    bad = row(19)
    bad[key] = None
    assert_invalid(parse_forecast, forecast_days([row(18), bad]), 3)


@pytest.mark.parametrize("value", ["2026-02-30", "2026-11-1", "19/11/2026", "", 20261119, True])
def test_forecast_row_bad_date(value):
    bad = row(19)
    bad["date"] = value
    assert_invalid(parse_forecast, forecast_days([row(18), bad]), 3)


@pytest.mark.parametrize("key", ["et0_mm", "rain_mm"])
@pytest.mark.parametrize("value", ["1.0", "", True, False, [1]])
def test_forecast_row_value_not_a_number(key, value):
    bad = row(19)
    bad[key] = value
    assert_invalid(parse_forecast, forecast_days([row(18), bad]), 3)


@pytest.mark.parametrize("key", ["et0_mm", "rain_mm"])
@pytest.mark.parametrize("value", [-0.1, -5, math.nan, math.inf, -math.inf])
def test_forecast_row_value_negative_or_not_finite(key, value):
    bad = row(19)
    bad[key] = value
    assert_invalid(parse_forecast, forecast_days([row(18), bad]), 3)


# ---- messages never hold a received value ----


def test_rule_and_message_hold_no_received_value():
    secret = "SECRET-VALUE-12345"
    bodies = [
        (parse_plot, plot_with(crop_id=secret, area_m2=secret)),
        (parse_plot, plot_with(planting_date=secret)),
        (parse_soil, {"available_water_mm_per_m": secret}),
        (parse_emitter, {"flow_lph": secret}),
    ]
    for call, body in bodies:
        error = assert_invalid(call, body)
        assert secret not in error.rule
        assert secret not in str(error)
    error = assert_invalid(parse_forecast, forecast_with(source=secret), 3)
    assert secret not in error.rule and secret not in str(error)
    error = assert_invalid(parse_forecast, forecast_with(fetched_at=secret), 3)
    assert secret not in error.rule and secret not in str(error)
