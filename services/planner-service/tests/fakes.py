"""Test fakes for the upstream client: a sleep that records, and a scripted HTTP transport."""

import asyncio
from collections.abc import Callable

import httpx

Outcome = httpx.Response | Exception | Callable[[httpx.Request], object]


class FakeSleep:
    """Replaces the real sleep: records every delay and returns at once (after one turn of the loop)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


class Script:
    """An httpx.MockTransport handler that plays the given outcomes in order.

    A response is returned, an exception is raised, a callable is called with the request.
    The last outcome repeats when the calls outnumber the outcomes.
    """

    def __init__(self, *outcomes: Outcome) -> None:
        assert outcomes, "a script needs at least one outcome"
        self._outcomes = outcomes
        self.requests: list[httpx.Request] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        index = min(len(self.requests), len(self._outcomes) - 1)
        self.requests.append(request)
        outcome = self._outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        result = outcome(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result  # type: ignore[return-value]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


async def block_forever(request: httpx.Request) -> httpx.Response:
    """A client that blocks before it connects and never returns."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


def json_response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)
