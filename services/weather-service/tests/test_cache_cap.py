import asyncio
from datetime import date

import pytest

from grid import Cell
from tests.test_service_rules import FAIL, fc, make

TODAY = date(2026, 11, 17)
A, B, C = Cell(1, 1), Cell(2, 2), Cell(3, 3)
LIMIT = 5


def good():
    return fc(TODAY)


def held(gate: asyncio.Event):
    """An outcome that waits for the gate, then answers: holds one fetch without holding the others."""

    async def outcome(lat, lon):
        await gate.wait()
        return good()

    return outcome


async def settle(turns: int = 10) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


def keys(svc):
    return set(svc._entries)


@pytest.mark.anyio
async def test_the_least_recently_used_cell_is_evicted_when_a_third_arrives():
    svc, prov, _ = make([good(), good(), good(), good()], CACHE_MAX_CELLS=2)
    for cell in (A, B, C):
        await svc.get(cell, 3)
    assert keys(svc) == {B, C}
    await svc.get(A, 3)  # A was forgotten: a new fetch
    assert prov.calls == 4


@pytest.mark.anyio
async def test_every_request_for_a_cell_makes_it_most_recently_used():
    svc, prov, _ = make([good(), good(), good()], CACHE_MAX_CELLS=2)
    await svc.get(A, 3)
    await svc.get(B, 3)
    await svc.get(A, 3)  # a fresh hit, no provider call, still counts as a use
    assert prov.calls == 2
    await svc.get(C, 3)
    assert keys(svc) == {A, C}


@pytest.mark.anyio
async def test_an_evicted_cell_during_an_outage_gets_unavailable_not_stale_rows():
    svc, prov, _ = make([good(), good(), good(), FAIL, FAIL, FAIL], CACHE_MAX_CELLS=2)
    for cell in (A, B, C):
        await svc.get(cell, 3)
    result = await svc.get(A, 3)
    assert result.kind == "unavailable" and result.rows == ()
    assert prov.calls == 6


@pytest.mark.anyio
async def test_a_cell_with_a_fetch_in_flight_is_not_evicted():
    gate = asyncio.Event()
    svc, prov, _ = make([held(gate), good(), good()], CACHE_MAX_CELLS=2)
    slow = asyncio.create_task(svc.get(A, 3))
    await settle()
    await svc.get(B, 3)
    await svc.get(C, 3)
    assert keys(svc) == {A, C}  # B was the oldest cell without a fetch in flight
    gate.set()
    assert (await asyncio.wait_for(slow, LIMIT)).kind == "fresh"
    assert prov.calls == 3


@pytest.mark.anyio
async def test_entries_older_than_the_stale_cap_are_dropped_on_insert():
    svc, _, clock = make([good(), good()], FRESH_FOR_SECONDS=100, STALE_MAX_AGE_SECONDS=1000)
    await svc.get(A, 3)
    clock.advance(1001)
    await svc.get(B, 3)  # a new entry: the dead one goes first, though the cap (2000) is far away
    assert keys(svc) == {B}


@pytest.mark.anyio
async def test_eviction_forgets_the_cooldown():
    svc, prov, _ = make([FAIL, FAIL, FAIL, good(), good(), good()], CACHE_MAX_CELLS=2, COOLDOWN_SECONDS=1000)
    assert (await svc.get(A, 3)).kind == "unavailable"
    await svc.get(B, 3)
    await svc.get(C, 3)  # A is evicted, and its cool-down with it
    assert A not in keys(svc)
    result = await svc.get(A, 3)
    assert result.kind == "fresh"
    assert prov.calls == 6


@pytest.mark.anyio
async def test_cells_in_flight_beyond_the_cap_finish_and_the_cache_shrinks_back():
    gate = asyncio.Event()
    cells = [Cell(i, i) for i in range(10, 15)]
    svc, prov, _ = make([held(gate) for _ in cells] + [good()], CACHE_MAX_CELLS=2)
    tasks = [asyncio.create_task(svc.get(c, 3)) for c in cells]
    await settle()
    assert prov.calls == 5 and len(svc._entries) == 5  # over the cap, none evicted, none blocked
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), LIMIT)
    assert all(r.kind == "fresh" for r in results)
    await svc.get(Cell(99, 99), 3)
    assert len(svc._entries) == 2
    assert Cell(99, 99) in keys(svc)
