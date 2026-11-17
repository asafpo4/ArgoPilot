from datetime import date

import pytest

from grid import Cell
from tests.test_service_rules import CELL, FAIL, fc, make

TODAY = date(2026, 11, 17)
OTHER = Cell(CELL.lat_index + 5, CELL.lon_index)
CYCLE = [FAIL, FAIL, FAIL]  # one failed cycle: three attempts


@pytest.mark.anyio
async def test_during_the_cooldown_there_is_no_provider_call_and_the_answer_is_immediate():
    svc, prov, clock = make([fc(TODAY), *CYCLE], FRESH_FOR_SECONDS=100)
    await svc.get(CELL, 3)
    clock.advance(100)
    first = await svc.get(CELL, 3)  # the cycle fails: stale answer, cool-down starts
    assert first.kind == "stale" and prov.calls == 4
    before = clock.monotonic()
    clock.advance(10)
    second = await svc.get(CELL, 3)
    assert prov.calls == 4  # no provider call
    assert second.kind == "stale" and len(second.rows) == 3
    assert clock.monotonic() == before + 10  # no wait, no sleep


@pytest.mark.anyio
async def test_during_the_cooldown_without_a_forecast_the_answer_is_unavailable_with_the_remaining_time():
    svc, prov, clock = make(CYCLE, COOLDOWN_SECONDS=30)
    first = await svc.get(CELL, 3)
    assert first.kind == "unavailable" and first.retry_after == 30
    clock.advance(10.5)  # 19.5 s left, rounded up
    assert (await svc.get(CELL, 3)).retry_after == 20
    clock.advance(19)  # 0.5 s left, at least 1
    assert (await svc.get(CELL, 3)).retry_after == 1
    assert prov.calls == 3


@pytest.mark.anyio
async def test_after_the_cooldown_a_new_cycle_starts():
    svc, prov, clock = make([*CYCLE, fc(TODAY)], COOLDOWN_SECONDS=30)
    await svc.get(CELL, 3)
    clock.advance(29.9)
    assert (await svc.get(CELL, 3)).kind == "unavailable" and prov.calls == 3
    clock.advance(0.1)  # the cool-down ends exactly now
    assert (await svc.get(CELL, 3)).kind == "fresh"
    assert prov.calls == 4


@pytest.mark.anyio
async def test_a_successful_fetch_clears_the_cooldown():
    svc, prov, clock = make([*CYCLE, fc(TODAY), fc(TODAY)], COOLDOWN_SECONDS=30, FRESH_FOR_SECONDS=100)
    await svc.get(CELL, 3)
    clock.advance(30)
    assert (await svc.get(CELL, 3)).kind == "fresh"
    assert svc._entries[CELL].cooldown_end is None
    clock.advance(100)  # stale by age; the next fetch is allowed at once and succeeds
    assert (await svc.get(CELL, 3)).kind == "fresh"
    assert prov.calls == 5


@pytest.mark.anyio
async def test_the_24_hour_cap_still_applies_during_a_cooldown():
    svc, prov, clock = make([fc(TODAY), *CYCLE], FRESH_FOR_SECONDS=100, STALE_MAX_AGE_SECONDS=1000, COOLDOWN_SECONDS=5000)
    await svc.get(CELL, 3)
    clock.advance(100)
    assert (await svc.get(CELL, 3)).kind == "stale"
    clock.advance(500)  # age 601: still under the cap
    assert (await svc.get(CELL, 3)).kind == "stale"
    clock.advance(500)  # age 1101: over the cap, cool-down still on
    result = await svc.get(CELL, 3)
    assert result.kind == "unavailable" and result.retry_after >= 1
    assert prov.calls == 4


@pytest.mark.anyio
async def test_a_cooldown_of_zero_turns_it_off():
    svc, prov, _ = make([*CYCLE, fc(TODAY)], COOLDOWN_SECONDS=0)
    assert (await svc.get(CELL, 3)).kind == "unavailable"
    assert (await svc.get(CELL, 3)).kind == "fresh"  # no waiting needed
    assert prov.calls == 4


@pytest.mark.anyio
async def test_a_cooldown_on_one_cell_does_not_affect_another():
    svc, prov, _ = make([*CYCLE, fc(TODAY)], COOLDOWN_SECONDS=30)
    assert (await svc.get(CELL, 3)).kind == "unavailable"
    assert (await svc.get(OTHER, 3)).kind == "fresh"
    assert prov.calls == 4
