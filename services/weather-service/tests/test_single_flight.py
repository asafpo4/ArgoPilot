import asyncio
import logging
from datetime import date

import pytest

from provider import Failure
from tests.fakes import FakeProvider
from tests.test_service_rules import CELL, FAIL, NOON, fc, make

TODAY = date(2026, 11, 17)
OTHER = type(CELL)(CELL.lat_index + 5, CELL.lon_index)
LIMIT = 5  # seconds: a hung cell must fail a test, not freeze the run


async def settle(turns: int = 10) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


def gated(outcomes):
    gate = asyncio.Event()
    svc, prov, clock = make(outcomes)
    prov.gate = gate
    return svc, prov, clock, gate


@pytest.mark.anyio
async def test_simultaneous_requests_for_one_cell_make_one_provider_call():
    svc, prov, _, gate = gated([fc(TODAY)])
    tasks = [asyncio.create_task(svc.get(CELL, 3)) for _ in range(20)]
    await settle()
    assert prov.calls == 1
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), LIMIT)
    assert prov.calls == 1
    assert all(r == results[0] for r in results)
    assert results[0].kind == "fresh" and len(results[0].rows) == 3


@pytest.mark.anyio
async def test_a_failure_is_shared_by_all_waiters():
    svc, prov, _, gate = gated([FAIL, FAIL, FAIL])
    tasks = [asyncio.create_task(svc.get(CELL, 3)) for _ in range(10)]
    await settle()
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), LIMIT)
    assert prov.calls == 3  # one cycle of three attempts
    assert all(r == results[0] for r in results)
    assert results[0].kind == "unavailable"


@pytest.mark.anyio
async def test_a_failure_with_a_stored_forecast_gives_every_waiter_the_same_stale_answer():
    svc, prov, clock = make([fc(TODAY), FAIL, FAIL, FAIL], FRESH_FOR_SECONDS=100)
    await svc.get(CELL, 3)
    clock.advance(100)
    gate = asyncio.Event()
    prov.gate = gate
    tasks = [asyncio.create_task(svc.get(CELL, 3)) for _ in range(5)]
    await settle()
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), LIMIT)
    assert prov.calls == 4
    assert all(r.kind == "stale" and r == results[0] for r in results)


@pytest.mark.anyio
async def test_a_waiter_that_is_cancelled_does_not_cancel_the_fetch_for_the_others():
    svc, prov, _, gate = gated([fc(TODAY)])
    first = asyncio.create_task(svc.get(CELL, 3))
    others = [asyncio.create_task(svc.get(CELL, 3)) for _ in range(3)]
    await settle()
    first.cancel()
    await settle()
    assert first.cancelled()
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*others), LIMIT)
    assert prov.calls == 1
    assert all(r.kind == "fresh" for r in results)


@pytest.mark.anyio
async def test_different_cells_do_not_block_each_other():
    svc, prov, _, gate = gated([fc(TODAY)])
    slow = asyncio.create_task(svc.get(CELL, 3))
    await settle()
    assert prov.calls == 1
    # The other cell gets its own provider; the gated one stays held.
    other_provider = FakeProvider([fc(TODAY)])
    svc.provider = _Router(prov, other_provider, {OTHER})
    result = await asyncio.wait_for(svc.get(OTHER, 3), LIMIT)
    assert result.kind == "fresh"
    assert not slow.done()
    gate.set()
    assert (await asyncio.wait_for(slow, LIMIT)).kind == "fresh"


class _Router:
    """Sends the node of the given cells to `other`, everything else to `main`."""

    def __init__(self, main, other, cells):
        from grid import node_for

        self.main, self.other = main, other
        self.nodes = {node_for(c) for c in cells}

    async def fetch(self, lat, lon):
        target = self.other if (lat, lon) in self.nodes else self.main
        return await target.fetch(lat, lon)


@pytest.mark.anyio
async def test_an_unexpected_exception_is_a_failed_cycle_and_the_next_request_works(caplog):
    marker = "SECRET-MARKER-123"

    def boom(lat, lon):
        raise RuntimeError(marker)

    svc, prov, clock = make([boom, boom, boom, fc(TODAY)])
    with caplog.at_level(logging.DEBUG):
        failed = await asyncio.wait_for(svc.get(CELL, 3), LIMIT)
    assert failed.kind == "unavailable"
    assert "RuntimeError" in caplog.text
    assert marker not in caplog.text
    assert svc._entries[CELL].inflight is None
    clock.advance(31)
    ok = await asyncio.wait_for(svc.get(CELL, 3), LIMIT)
    assert ok.kind == "fresh"
    assert prov.calls == 4


@pytest.mark.anyio
async def test_an_error_outside_the_provider_call_is_a_failed_cycle_and_clears_the_marker(caplog):
    marker = "SECRET-MARKER-456"
    svc, prov, clock = make([FAIL, fc(TODAY)])

    async def bad_sleep(seconds):
        raise RuntimeError(marker)

    good_sleep = clock.sleep
    clock.sleep = bad_sleep
    with caplog.at_level(logging.DEBUG):
        failed = await asyncio.wait_for(svc.get(CELL, 3), LIMIT)
    assert failed.kind == "unavailable"
    assert marker not in caplog.text and "RuntimeError" in caplog.text
    assert svc._entries[CELL].inflight is None
    assert svc._entries[CELL].cooldown_end is not None
    clock.sleep = good_sleep
    assert (await asyncio.wait_for(svc.get(CELL, 3), LIMIT)).kind == "fresh"


@pytest.mark.anyio
async def test_cancelling_the_cycle_clears_the_in_flight_marker():
    svc, prov, _, gate = gated([fc(TODAY), fc(TODAY)])
    waiter = asyncio.create_task(svc.get(CELL, 3))
    await settle()
    assert svc._entries[CELL].inflight is not None
    await asyncio.wait_for(svc.aclose(), LIMIT)
    assert svc._entries[CELL].inflight is None
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, LIMIT)
    gate.set()
    again = await asyncio.wait_for(svc.get(CELL, 3), LIMIT)
    assert again.kind == "fresh"


@pytest.mark.anyio
async def test_closing_before_the_cycle_has_started_still_clears_the_marker():
    svc, prov, _, gate = gated([fc(TODAY)])
    waiter = asyncio.create_task(svc.get(CELL, 3))
    await asyncio.sleep(0)  # the request ran up to its first await; the cycle task has not started
    await asyncio.wait_for(svc.aclose(), LIMIT)
    assert svc._entries[CELL].inflight is None
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.anyio
async def test_no_await_between_the_check_and_the_start():
    svc, prov, _ = make([fc(TODAY)])
    results = await asyncio.wait_for(asyncio.gather(*(svc.get(CELL, 2) for _ in range(30))), LIMIT)
    assert prov.calls == 1
    assert all(r.kind == "fresh" for r in results)
