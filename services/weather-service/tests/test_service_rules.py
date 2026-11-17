import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from config import Settings
from forecast_service import ForecastService
from grid import Cell
from provider import Failure
from tests.fakes import FakeClock, FakeProvider, good_forecast

CELL = Cell(481, 116)
UTC = timezone.utc
NOON = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
FAIL = Failure("timeout")


def settings(**kw) -> Settings:
    return Settings(PROVIDER_BASE_URL="http://localhost:1", **kw)


def make(outcomes, start=NOON, **kw):
    clock = FakeClock(start)
    provider = FakeProvider(outcomes)
    return ForecastService(provider, clock, settings(**kw)), provider, clock


def fc(first: date, tz="UTC"):
    return good_forecast(first, tz)


@pytest.mark.anyio
async def test_a_fresh_forecast_makes_no_provider_call():
    svc, prov, clock = make([fc(date(2026, 11, 17))])
    first = await svc.get(CELL, 3)
    clock.advance(60)
    second = await svc.get(CELL, 3)
    assert prov.calls == 1
    assert first.kind == second.kind == "fresh"
    assert first.fetched_at == second.fetched_at == NOON


@pytest.mark.anyio
async def test_expiry_by_age_at_the_fresh_limit():
    svc, prov, clock = make([fc(date(2026, 11, 17)), fc(date(2026, 11, 17))], FRESH_FOR_SECONDS=100)
    await svc.get(CELL, 1)
    clock.advance(99)
    await svc.get(CELL, 1)
    assert prov.calls == 1
    clock.advance(1)  # age is exactly the limit
    await svc.get(CELL, 1)
    assert prov.calls == 2


@pytest.mark.anyio
@pytest.mark.parametrize("days", [1, 7])
async def test_a_fresh_answer_has_exactly_days_rows(days):
    svc, _, _ = make([fc(date(2026, 11, 17))])
    result = await svc.get(CELL, days)
    assert len(result.rows) == days
    assert result.rows[0].date == date(2026, 11, 17)


# Fetched at the given UTC time, local date D; two hours later (fresh by age) the local date is D+1.
@pytest.mark.anyio
@pytest.mark.parametrize(
    "tz, fetch_utc, first",
    [
        ("Pacific/Auckland", datetime(2026, 11, 17, 9, 0, tzinfo=UTC), date(2026, 11, 17)),  # +13: 22:00 local
        ("America/Los_Angeles", datetime(2026, 11, 17, 6, 0, tzinfo=UTC), date(2026, 11, 16)),  # -8: 22:00 local
        ("Asia/Kolkata", datetime(2026, 11, 17, 17, 30, tzinfo=UTC), date(2026, 11, 17)),  # +5:30: 23:00 local
        ("Asia/Kathmandu", datetime(2026, 11, 17, 17, 45, tzinfo=UTC), date(2026, 11, 17)),  # +5:45: 23:30 local
    ],
)
async def test_midnight_expiry_refetches_though_fresh_by_age(tz, fetch_utc, first):
    svc, prov, clock = make([fc(first, tz), fc(first + timedelta(days=1), tz)], start=fetch_utc)
    await svc.get(CELL, 2)
    clock.advance(1800)  # still before local midnight for Kathmandu? 23:30 + 30 min = midnight
    clock.advance(5400)  # now past local midnight everywhere, and well inside the 3 hours
    result = await svc.get(CELL, 2)
    assert prov.calls == 2
    assert result.kind == "fresh"
    assert result.rows[0].date == first + timedelta(days=1)


@pytest.mark.anyio
async def test_midnight_expiry_with_a_failing_provider_serves_stale_rows_from_today():
    first = date(2026, 11, 17)
    start = datetime(2026, 11, 17, 17, 30, tzinfo=UTC)  # 23:00 in Kolkata
    svc, prov, clock = make([fc(first, "Asia/Kolkata"), FAIL, FAIL, FAIL], start=start)
    await svc.get(CELL, 7)
    clock.advance(2 * 3600)
    result = await svc.get(CELL, 7)
    assert result.kind == "stale"
    assert result.rows[0].date == date(2026, 11, 18)
    assert len(result.rows) == 6


@pytest.mark.anyio
async def test_cells_at_the_date_line_have_different_local_dates():
    # 2026-11-17 12:30 UTC is 2026-11-18 00:30 in +12 and 2026-11-17 in -12.
    now = datetime(2026, 11, 17, 12, 30, tzinfo=UTC)
    east_first, west_first = date(2026, 11, 18), date(2026, 11, 17)
    svc, prov, _ = make([fc(east_first, "Pacific/Fiji"), fc(west_first, "Etc/GMT+12")], start=now)
    east = await svc.get(Cell(0, 1800), 1)  # lon 179.99 rounds to the 180.0 node
    west = await svc.get(Cell(0, -1800), 1)
    assert east.rows[0].date == east_first
    assert west.rows[0].date == west_first
    assert prov.calls == 2
    assert (await svc.get(Cell(0, 1800), 1)).kind == "fresh"
    assert (await svc.get(Cell(0, -1800), 1)).kind == "fresh"
    assert prov.calls == 2


@pytest.mark.anyio
async def test_a_stale_answer_after_the_retries_makes_three_calls_and_waits_the_delays():
    svc, prov, clock = make([fc(date(2026, 11, 17)), FAIL, FAIL, FAIL], FRESH_FOR_SECONDS=100)
    await svc.get(CELL, 2)
    clock.advance(100)
    before = clock.monotonic()
    result = await svc.get(CELL, 2)
    assert result.kind == "stale"
    assert prov.calls == 4  # one good fetch, then three failing attempts
    assert clock.monotonic() - before == pytest.approx(2 * 0.5)


@pytest.mark.anyio
async def test_stale_rows_before_today_are_dropped_and_the_list_is_shorter():
    svc, _, clock = make([fc(date(2026, 11, 17)), FAIL, FAIL, FAIL])
    await svc.get(CELL, 7)
    clock.advance(24 * 3600 - 3600)  # 11:00 next day: inside the cap, the first row is yesterday
    result = await svc.get(CELL, 7)
    assert result.kind == "stale"
    assert [r.date for r in result.rows][0] == date(2026, 11, 18)
    assert len(result.rows) == 6


@pytest.mark.anyio
async def test_a_stale_answer_keeps_its_own_fetched_at():
    svc, _, clock = make([fc(date(2026, 11, 17)), FAIL, FAIL, FAIL])
    await svc.get(CELL, 2)
    clock.advance(4 * 3600)
    result = await svc.get(CELL, 2)
    assert result.kind == "stale"
    assert result.fetched_at == NOON


@pytest.mark.anyio
async def test_a_stale_answer_is_never_empty():
    svc, _, clock = make([fc(date(2026, 11, 17)), FAIL, FAIL, FAIL], STALE_MAX_AGE_SECONDS=10 * 86400)
    await svc.get(CELL, 7)
    clock.advance(8 * 86400)  # every row is in the past, the age is under the cap
    result = await svc.get(CELL, 7)
    assert result.kind == "unavailable"
    assert result.rows == ()


@pytest.mark.anyio
async def test_the_24_hour_cap_ends_stale_service():
    svc, _, clock = make([fc(date(2026, 11, 17)), FAIL, FAIL, FAIL, FAIL, FAIL, FAIL])
    await svc.get(CELL, 1)
    # The age is judged when the answer is built, after the retries (spec 3.4 step 5), so the margin of
    # 5 seconds is larger than the 1 second that the two retry delays add.
    clock.advance(86400 - 5)
    assert (await svc.get(CELL, 1)).kind == "stale"
    clock.advance(5)
    result = await svc.get(CELL, 1)
    assert result.kind == "unavailable"
    assert result.retry_after is not None and result.retry_after >= 1


@pytest.mark.anyio
async def test_no_forecast_and_a_failing_provider_is_unavailable():
    svc, prov, _ = make([FAIL, FAIL, FAIL])
    result = await svc.get(CELL, 3)
    assert result.kind == "unavailable"
    assert result.rows == () and result.fetched_at is None
    assert prov.calls == 3


@pytest.mark.anyio
@pytest.mark.parametrize("days, expected", [(7, 5), (6, 5), (5, 5)])
async def test_daylight_saving_two_midnights(days, expected):
    # Berlin: 2027-03-28 is 23 hours long. Fetched 23:30 local on the 27th, asked 00:10 local on the 29th.
    fetched = datetime(2027, 3, 27, 22, 30, tzinfo=UTC)
    svc, _, clock = make([fc(date(2027, 3, 27), "Europe/Berlin"), FAIL, FAIL, FAIL], start=fetched)
    await svc.get(CELL, 7)
    clock.advance((datetime(2027, 3, 28, 22, 10, tzinfo=UTC) - fetched).total_seconds())
    result = await svc.get(CELL, days)
    assert result.kind == "stale"
    assert [r.date for r in result.rows] == [date(2027, 3, 29) + timedelta(days=i) for i in range(5)]
    assert len(result.rows) == expected


@pytest.mark.anyio
async def test_a_successful_fetch_replaces_the_stored_forecast():
    old, new = fc(date(2026, 11, 17)), good_forecast(date(2026, 11, 17))
    new = type(new)(rows=tuple(type(r)(r.date, r.et0_mm + 10, r.rain_mm) for r in new.rows), tz=new.tz)
    svc, _, clock = make([old, new], FRESH_FOR_SECONDS=100)
    first = await svc.get(CELL, 1)
    clock.advance(100)
    second = await svc.get(CELL, 1)
    assert second.rows[0].et0_mm == first.rows[0].et0_mm + 10
    assert second.fetched_at == NOON + timedelta(seconds=100)
    assert (await svc.get(CELL, 1)).rows == second.rows


@pytest.mark.anyio
async def test_an_unavailable_result_has_retry_after_from_the_cooldown_setting():
    svc, _, _ = make([FAIL, FAIL, FAIL, FAIL, FAIL, FAIL], COOLDOWN_SECONDS=30, PROVIDER_RETRY_DELAY_SECONDS=0)
    assert (await svc.get(CELL, 1)).retry_after == 30


@pytest.mark.anyio
async def test_failed_attempts_are_logged_with_kinds_only(caplog):
    svc, _, _ = make([Failure("status 500"), Failure("timeout"), Failure("transport")])
    with caplog.at_level(logging.WARNING, logger="weather.service"):
        await svc.get(CELL, 1)
    text = caplog.text
    assert text.count("attempt failed") == 3 and text.count("cycle failed") == 1
    assert "status 500" in text and "timeout" in text and "transport" in text
