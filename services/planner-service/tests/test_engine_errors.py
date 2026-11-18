from dataclasses import replace
from datetime import date, timedelta

import pytest

from engine import PlotInput, WeatherRow, plan

PLOT = PlotInput("tomato", date(2026, 6, 1), 1000.0, 1.5, 0.4, 1.0, 175.0)
START = date(2026, 8, 10)


def rows(*pairs):
    return [WeatherRow(START + timedelta(days=i), et0, rain) for i, (et0, rain) in enumerate(pairs)]


GOOD = rows((6.0, 0.0), (5.0, 1.0))


@pytest.mark.parametrize(
    "field",
    ["area_m2", "row_spacing_m", "emitter_spacing_m", "emitter_flow_lph", "soil_mm_per_m"],
)
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_plot_numbers(field, bad):
    with pytest.raises(ValueError):
        plan(replace(PLOT, **{field: bad}), GOOD)


def test_unknown_crop():
    with pytest.raises(ValueError):
        plan(replace(PLOT, crop_id="wheat"), GOOD)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), -0.1])
@pytest.mark.parametrize("column", ["et0", "rain"])
def test_bad_weather_numbers(column, bad):
    pair = (bad, 0.0) if column == "et0" else (5.0, bad)
    with pytest.raises(ValueError):
        plan(PLOT, rows((6.0, 0.0), pair))


def test_empty_rows():
    with pytest.raises(ValueError):
        plan(PLOT, [])


def test_date_gap():
    bad = [WeatherRow(START, 5.0, 0.0), WeatherRow(START + timedelta(days=2), 5.0, 0.0)]
    with pytest.raises(ValueError):
        plan(PLOT, bad)


def test_repeated_date():
    bad = [WeatherRow(START, 5.0, 0.0), WeatherRow(START, 5.0, 0.0)]
    with pytest.raises(ValueError):
        plan(PLOT, bad)


def test_wrong_order():
    bad = [WeatherRow(START + timedelta(days=1), 5.0, 0.0), WeatherRow(START, 5.0, 0.0)]
    with pytest.raises(ValueError):
        plan(PLOT, bad)


def test_message_has_no_values():
    with pytest.raises(ValueError) as caught:
        plan(replace(PLOT, area_m2=-123.456), GOOD)
    assert "123.456" not in str(caught.value)


def test_huge_area_gives_non_finite_result():
    # Finite input, but litres and flow overflow to infinity: never a plan with Infinity in it.
    with pytest.raises(ValueError):
        plan(replace(PLOT, area_m2=1e308), rows((6.0, 0.0)))
