"""The three hand-calculated cases of spec 5.4, checked against every intermediate value."""

from datetime import date, timedelta

import pytest

from engine import PlotInput, WeatherRow, plan

NORTH = PlotInput(
    crop_id="tomato",
    planting_date=date(2026, 3, 1),
    area_m2=1000.0,
    row_spacing_m=1.5,
    emitter_spacing_m=0.4,
    emitter_flow_lph=1.0,
    soil_mm_per_m=175.0,
)

EAST = PlotInput(
    crop_id="bell-pepper",
    planting_date=date(2026, 4, 12),
    area_m2=800.0,
    row_spacing_m=1.5,
    emitter_spacing_m=0.4,
    emitter_flow_lph=1.6,
    soil_mm_per_m=200.0,
)


def make_rows(start: date, *pairs) -> list[WeatherRow]:
    return [WeatherRow(start + timedelta(days=i), et0, rain) for i, (et0, rain) in enumerate(pairs)]


def test_case_a_task_example():
    result = plan(NORTH, make_rows(date(2026, 6, 9), (6.0, 0.0)))
    day = result.days[0]
    assert day.d == 100
    assert day.stage == "mid"
    assert day.kc == pytest.approx(1.15, abs=1e-6)
    assert day.etc_mm == pytest.approx(6.9, abs=1e-6)
    assert result.taw_mm == pytest.approx(122.5, abs=1e-6)
    assert day.p == pytest.approx(0.324, abs=1e-6)
    assert day.raw_mm == pytest.approx(39.69, abs=1e-6)
    assert day.irrigation_mm == pytest.approx(6.9, abs=1e-6)
    assert day.litres == pytest.approx(6900, abs=1e-6)
    assert result.flow_lph == pytest.approx(1000 / 0.6, abs=1e-6)
    assert day.run_minutes == pytest.approx(248.4, abs=1e-6)
    assert day.bucket_mm == pytest.approx(82.81, abs=1e-6)
    assert day.trigger_mm == pytest.approx(82.81, abs=1e-6)


def test_case_b_rain_and_small_irrigation():
    rows = make_rows(
        date(2026, 8, 10),
        (6.25, 0.0),
        (6.25, 19.7),
        (6.25, 0.5),
        (6.25, 0.0),
        (6.25, 0.0),
    )
    result = plan(NORTH, rows)
    days = result.days
    assert [day.d for day in days] == [162, 163, 164, 165, 166]
    assert all(day.stage == "after_cycle" for day in days)
    assert [day.kc for day in days] == pytest.approx([0.8] * 5, abs=1e-6)
    assert [day.etc_mm for day in days] == pytest.approx([5.0] * 5, abs=1e-6)
    assert [day.p for day in days] == pytest.approx([0.40] * 5, abs=1e-6)
    assert [day.raw_mm for day in days] == pytest.approx([49.0] * 5, abs=1e-6)
    assert [day.rain_counted_mm for day in days] == pytest.approx(
        [0.0, 19.7, 0.0, 0.0, 0.0], abs=1e-6
    )
    assert [day.irrigation_mm for day in days] == pytest.approx([5.0, 0, 0, 0, 0.3], abs=1e-6)
    assert [day.litres for day in days] == pytest.approx([5000, 0, 0, 0, 300], abs=1e-6)
    assert [day.run_minutes for day in days] == pytest.approx([180, 0, 0, 0, 10.8], abs=1e-6)
    assert [day.bucket_mm for day in days] == pytest.approx(
        [73.5, 88.2, 83.2, 78.2, 73.5], abs=1e-6
    )
    assert [day.trigger_mm for day in days] == pytest.approx([73.5] * 5, abs=1e-6)


def test_case_c_pepper_development():
    result = plan(EAST, make_rows(date(2026, 6, 1), (5.6, 0.0), (5.6, 0.0)))
    days = result.days
    assert result.taw_mm == pytest.approx(100.0, abs=1e-6)
    assert [day.d for day in days] == [50, 51]
    assert [day.stage for day in days] == ["development", "development"]
    assert [day.kc for day in days] == pytest.approx([6 / 7, 0.87], abs=1e-6)
    assert [day.etc_mm for day in days] == pytest.approx([4.8, 4.872], abs=1e-6)
    assert [day.p for day in days] == pytest.approx([0.308, 0.30512], abs=1e-6)
    assert [day.raw_mm for day in days] == pytest.approx([30.8, 30.512], abs=1e-6)
    assert [day.irrigation_mm for day in days] == pytest.approx([4.8, 5.16], abs=1e-6)
    assert [day.litres for day in days] == pytest.approx([3840, 4128], abs=1e-6)
    assert result.flow_lph == pytest.approx(800 / 0.6 * 1.6, abs=1e-6)
    assert [day.run_minutes for day in days] == pytest.approx([108.0, 116.1], abs=1e-6)
    assert [day.bucket_mm for day in days] == pytest.approx([69.2, 69.488], abs=1e-6)
