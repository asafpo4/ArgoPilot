import asyncio
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from provider import Failure
from tests.fakes import FakeProvider, good_forecast

LAT, LON = Decimal("48.1"), Decimal("11.6")
TODAY = date(2026, 11, 17)


@pytest.mark.anyio
async def test_it_returns_scripted_outcomes_in_order_and_counts_calls():
    first, second = good_forecast(TODAY), Failure("timeout")
    fake = FakeProvider([first, second])
    assert fake.calls == 0
    assert await fake.fetch(LAT, LON) is first
    assert await fake.fetch(LAT, LON) is second
    assert fake.calls == 2
    assert fake.points == [(LAT, LON), (LAT, LON)]
    with pytest.raises(AssertionError):
        await fake.fetch(LAT, LON)


@pytest.mark.anyio
async def test_a_gate_holds_the_fetch_until_released():
    gate = asyncio.Event()
    fake = FakeProvider([good_forecast(TODAY)], gate=gate)
    task = asyncio.create_task(fake.fetch(LAT, LON))
    for _ in range(5):
        await asyncio.sleep(0)
    assert fake.calls == 1  # the call is counted while it is held
    assert not task.done()
    gate.set()
    assert await task == good_forecast(TODAY)


@pytest.mark.anyio
async def test_a_callable_outcome_can_raise_an_unexpected_exception():
    def boom(lat: Decimal, lon: Decimal) -> object:
        raise RuntimeError("unexpected")

    async def late(lat: Decimal, lon: Decimal) -> object:
        return Failure("transport")

    fake = FakeProvider([boom, late])
    with pytest.raises(RuntimeError):
        await fake.fetch(LAT, LON)
    assert await fake.fetch(LAT, LON) == Failure("transport")
    assert fake.calls == 2


def test_good_forecast_helper_builds_seven_rows_for_a_zone():
    forecast = good_forecast(date(2026, 12, 29), "Asia/Kolkata")
    dates = [row.date for row in forecast.rows]
    assert len(dates) == 7
    assert dates[0] == date(2026, 12, 29) and dates[-1] == date(2027, 1, 4)
    assert all((b - a).days == 1 for a, b in zip(dates, dates[1:]))
    assert forecast.tz == ZoneInfo("Asia/Kolkata")
    assert all(row.et0_mm >= 0 and row.rain_mm >= 0 for row in forecast.rows)
