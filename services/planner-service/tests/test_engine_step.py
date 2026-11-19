from datetime import date, timedelta

import pytest

from engine import CROPS, PlotInput, WeatherRow, plan

MID_START = date(2026, 8, 10)  # day 70 of a tomato planted 2026-06-01: mid, Kc 1.15


def make_plot(**changes) -> PlotInput:
    values = dict(
        crop_id="tomato",
        planting_date=date(2026, 6, 1),
        area_m2=1000.0,
        row_spacing_m=1.5,
        emitter_spacing_m=0.4,
        emitter_flow_lph=1.0,
        soil_mm_per_m=175.0,
    )
    values.update(changes)
    return PlotInput(**values)


def make_rows(*pairs, start=MID_START) -> list[WeatherRow]:
    return [WeatherRow(start + timedelta(days=i), et0, rain) for i, (et0, rain) in enumerate(pairs)]


def test_task_example_litres_and_minutes():
    day = plan(make_plot(), make_rows((6.0, 0.0))).days[0]
    assert day.etc_mm == pytest.approx(6.9)
    assert day.p == pytest.approx(0.324)
    assert day.irrigation_mm == pytest.approx(6.9)
    assert day.litres == pytest.approx(6900)
    assert day.run_minutes == pytest.approx(248.4)
    assert plan(make_plot(), make_rows((6.0, 0.0))).flow_lph == pytest.approx(1666.6667, rel=1e-6)


def test_p_follows_formula_and_limits():
    # ETc 5 gives the table p (Kc 1.15, so ET0 = 5 / 1.15).
    result = plan(make_plot(), make_rows((5 / 1.15, 0.0)))
    assert result.days[0].p == pytest.approx(0.40)
    # A huge ETc clamps at 0.1.
    assert plan(make_plot(), make_rows((100.0, 0.0))).days[0].p == 0.1
    # ETc 0 gives table p + 0.2.
    assert plan(make_plot(), make_rows((0.0, 0.0))).days[0].p == pytest.approx(0.6)
    pepper = make_plot(crop_id="bell-pepper")
    assert plan(pepper, make_rows((0.0, 0.0))).days[0].p == pytest.approx(0.5)
    # The upper limit 0.8 cannot be reached by the formula with ETc >= 0: tomato 0.6 and
    # pepper 0.5 are the largest values, so p never exceeds 0.8.
    for crop in CROPS:
        assert plan(make_plot(crop_id=crop), make_rows((0.0, 0.0))).days[0].p <= 0.8


def test_rain_threshold():
    et0 = 5.0
    threshold = 0.2 * et0
    below = plan(make_plot(), make_rows((et0, threshold - 1e-9))).days[0]
    assert below.rain_counted_mm == 0.0
    at = plan(make_plot(), make_rows((et0, threshold))).days[0]
    assert at.rain_counted_mm == threshold
    dry = plan(make_plot(), make_rows((0.0, 0.3))).days[0]
    assert dry.rain_counted_mm == 0.3


def test_before_clamped_at_zero_and_taw():
    # Rain far above the bucket: nothing is carried, depletion is 0.
    rows = make_rows((5.0, 60.0), (5.0, 0.0))
    result = plan(make_plot(), rows)
    assert result.days[0].depletion_mm == 0.0
    assert result.days[0].bucket_mm == pytest.approx(result.taw_mm)
    # The next day starts from 0, so a dry day of ETc 5.75 does not reach RAW: no irrigation.
    assert result.days[1].irrigation_mm == 0.0
    assert result.days[1].depletion_mm == pytest.approx(5.75)
    # A tiny flow keeps depletion at or below TAW.
    slow = make_plot(emitter_flow_lph=0.001)
    result = plan(slow, make_rows(*[(12.0, 0.0)] * 30))
    assert all(day.depletion_mm <= result.taw_mm for day in result.days)
    last = result.days[-1]
    assert last.depletion_mm + last.irrigation_mm == pytest.approx(result.taw_mm)


def test_start_at_trigger_and_overshoot_only():
    result = plan(make_plot(), make_rows((6.0, 0.0), (6.0, 0.0)))
    first = result.days[0]
    assert result.start_bucket_mm == pytest.approx(first.trigger_mm)
    # Day 1 starts at D = RAW, so it irrigates only the day's ETc.
    assert first.irrigation_mm == pytest.approx(first.etc_mm)
    assert result.days[1].irrigation_mm == pytest.approx(result.days[1].etc_mm)


def test_bucket_equals_trigger_when_irrigated_and_not_capped():
    result = plan(make_plot(), make_rows(*[(6.0, 0.0)] * 5))
    for day in result.days:
        assert day.irrigation_mm > 0 and not day.capped
        assert day.bucket_mm == pytest.approx(day.trigger_mm)


def test_cap_1440_minutes_carries_depletion():
    # Application rate 0.001 / 0.6 mm/h is far below ETc / 24 h.
    slow = make_plot(emitter_flow_lph=0.01)
    result = plan(slow, make_rows((6.0, 0.0), (6.0, 0.0)))
    day1, day2 = result.days
    assert day1.capped
    assert day1.run_minutes == 1440
    assert day1.bucket_mm < day1.trigger_mm
    assert day1.irrigation_mm == pytest.approx(24 * 0.01 / 0.6)
    # The second day starts from the depletion left by the first.
    before2 = day1.depletion_mm + day2.etc_mm
    assert day2.depletion_mm == pytest.approx(min(result.taw_mm, before2) - day2.irrigation_mm)
    assert day2.depletion_mm > day1.depletion_mm


def test_no_ks():
    slow = make_plot(emitter_flow_lph=0.01)
    result = plan(slow, make_rows(*[(6.0, 0.0)] * 3))
    assert result.days[0].capped
    for day, row in zip(result.days, make_rows(*[(6.0, 0.0)] * 3)):
        assert day.etc_mm == day.kc * row.et0_mm


def test_warnings():
    crop = CROPS["tomato"]
    length = crop.cycle_length
    planting = date(2026, 1, 1)
    plot = make_plot(planting_date=planting)

    past = plan(plot, make_rows((5.0, 0.0), start=planting + timedelta(days=length + 3)))
    assert [(w.code, w.numbers) for w in past.warnings] == [
        ("planting_date_past_cycle", {"days_past_cycle": 3})
    ]
    future = plan(plot, make_rows((5.0, 0.0), start=planting - timedelta(days=4)))
    assert [(w.code, w.numbers) for w in future.warnings] == [
        ("planting_date_in_future", {"days_until_planting": 4})
    ]
    # The first day is inside the cycle: no warning, even when the plan crosses L later.
    crossing = plan(plot, make_rows(*[(5.0, 0.0)] * 4, start=planting + timedelta(days=length - 1)))
    assert crossing.warnings == ()
    assert crossing.days[-1].stage == "after_cycle"
    # d1 == L is still inside the cycle.
    on_last = plan(plot, make_rows((5.0, 0.0), start=planting + timedelta(days=length)))
    assert on_last.warnings == ()
    # d1 == 0 is not in the future.
    assert plan(plot, make_rows((5.0, 0.0), start=planting)).warnings == ()


def test_future_planting_is_initial_kc_ini():
    plot = make_plot(planting_date=date(2026, 9, 1))
    day = plan(plot, make_rows((5.0, 0.0), start=date(2026, 8, 31))).days[0]
    assert day.d == -1
    assert day.stage == "initial"
    assert day.kc == CROPS["tomato"].kc[0]
