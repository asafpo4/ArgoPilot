"""The fakes that every later test relies on: the clock and the provider answer builder."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from fakes import DROP, FakeClock, provider_body

START = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)


def test_fake_clock_moves_now_and_monotonic_together() -> None:
    clock = FakeClock(START)
    before_now, before_monotonic = clock.now(), clock.monotonic()
    clock.advance(90)
    assert clock.now() - before_now == timedelta(seconds=90)
    assert clock.monotonic() - before_monotonic == 90
    assert clock.now().utcoffset() == timedelta(0)  # still UTC and timezone-aware


@pytest.mark.anyio
async def test_fake_sleep_advances_time_at_once_and_yields() -> None:
    clock = FakeClock(START)
    seen_by_other: list[float] = []

    async def other() -> None:
        seen_by_other.append(clock.monotonic())

    task = asyncio.ensure_future(other())
    await clock.sleep(5)
    assert clock.monotonic() == 5
    assert clock.now() == START + timedelta(seconds=5)
    # The time had already moved when control went to the other task: the sleep advanced, then yielded.
    assert seen_by_other == [5.0]
    await task


@pytest.mark.anyio
async def test_fake_clock_never_goes_backwards() -> None:
    clock = FakeClock(START)
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        await clock.sleep(-1)


def test_provider_body_has_seven_rows_starting_at_the_given_date_in_the_given_zone() -> None:
    body = provider_body(date(2026, 11, 16), tz="Asia/Kolkata", utc_offset_seconds=19800)
    assert body["timezone"] == "Asia/Kolkata"
    assert body["utc_offset_seconds"] == 19800
    assert body["daily_units"] == {
        "time": "iso8601",
        "et0_fao_evapotranspiration": "mm",
        "precipitation_sum": "mm",
    }
    daily = body["daily"]
    assert len(daily["time"]) == 7
    assert daily["time"][0] == "2026-11-16"
    assert daily["time"][-1] == "2026-11-22"
    assert [date.fromisoformat(t) for t in daily["time"]] == [
        date(2026, 11, 16) + timedelta(days=i) for i in range(7)
    ]
    assert len(daily["et0_fao_evapotranspiration"]) == 7
    assert len(daily["precipitation_sum"]) == 7


def test_provider_body_rows_parameter_sets_the_length() -> None:
    body = provider_body(date(2026, 11, 16), rows=8)
    assert len(body["daily"]["time"]) == 8
    assert len(body["daily"]["et0_fao_evapotranspiration"]) == 8
    assert len(body["daily"]["precipitation_sum"]) == 8


def test_provider_body_overrides_replace_a_field_or_drop_it() -> None:
    replaced = provider_body(date(2026, 11, 16), latitude=48.1)
    assert replaced["latitude"] == 48.1
    dropped = provider_body(date(2026, 11, 16), timezone=DROP, elevation=DROP)
    assert "timezone" not in dropped
    assert "elevation" not in dropped
    assert "daily" in dropped  # only the named fields are touched
    replaced_daily = provider_body(date(2026, 11, 16), daily={"time": []})
    assert replaced_daily["daily"] == {"time": []}
