"""Test fakes: a clock that the test moves, and an Open-Meteo-shaped answer that the test can break.

The provider's field names live here, and in provider.py only, as spec 5.3 requires for code that
imitates the provider. Every other module refers to the provider through its own names.
"""

import asyncio
import inspect
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from provider import Day, Failure, ProviderForecast

Outcome = ProviderForecast | Failure | Callable[[Decimal, Decimal], object]


class _Drop:
    """Marks an override that removes a field from the body."""

    def __repr__(self) -> str:
        return "DROP"


DROP = _Drop()


class FakeClock:
    """A clock for tests. `now` and `monotonic` move together; `sleep` moves time at once, then yields."""

    def __init__(self, start: datetime) -> None:
        self._start = start
        self._elapsed = 0.0

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        return self._elapsed

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("time does not go backwards")
        self._elapsed += seconds

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)  # Give other tasks a turn, now that the time has moved.


def provider_body(
    first_date: date,
    *,
    tz: str = "UTC",
    utc_offset_seconds: int = 0,
    rows: int = 7,
    **overrides: object,
) -> dict[str, object]:
    """An Open-Meteo-shaped answer with `rows` consecutive dates starting at `first_date`.

    Each keyword replaces the top-level field of that name; `DROP` removes it. A test that needs a deeper
    change (for example a null inside `daily`) changes the returned dict.
    """
    times = [(first_date + timedelta(days=i)).isoformat() for i in range(rows)]
    body: dict[str, object] = {
        "latitude": 48.1,
        "longitude": 11.6,
        "generationtime_ms": 0.5,
        "utc_offset_seconds": utc_offset_seconds,
        "timezone": tz,
        "timezone_abbreviation": "GMT",
        "elevation": 500.0,
        "daily_units": {
            "time": "iso8601",
            "et0_fao_evapotranspiration": "mm",
            "precipitation_sum": "mm",
        },
        "daily": {
            "time": times,
            "et0_fao_evapotranspiration": [round(3.0 + 0.1 * i, 1) for i in range(rows)],
            "precipitation_sum": [round(1.5 * (i % 2), 1) for i in range(rows)],
        },
    }
    for key, value in overrides.items():
        if value is DROP:
            body.pop(key, None)
        else:
            body[key] = value
    return body


def good_forecast(first_date: date, tz: str = "UTC") -> ProviderForecast:
    """A valid ProviderForecast: seven consecutive rows from `first_date`, in the zone `tz`."""
    rows = tuple(
        Day(first_date + timedelta(days=i), round(3.0 + 0.1 * i, 1), round(1.5 * (i % 2), 1))
        for i in range(7)
    )
    return ProviderForecast(rows=rows, tz=ZoneInfo(tz))


class FakeProvider:
    """A Provider with scripted outcomes, used in order. One call to `fetch` is one attempt.

    An outcome is a ProviderForecast, a Failure, or a callable `(lat, lon) -> outcome` (it may raise, or be
    async). Running past the script is a test error. `calls` counts every call, also one that is held at
    the gate. With a `gate` (an asyncio.Event), a call waits for `gate.set()` before it answers.
    """

    def __init__(self, outcomes: Sequence[Outcome], *, gate: asyncio.Event | None = None) -> None:
        self._outcomes = list(outcomes)
        self.gate = gate
        self.calls = 0
        self.points: list[tuple[Decimal, Decimal]] = []

    async def fetch(self, lat: Decimal, lon: Decimal) -> ProviderForecast | Failure:
        index = self.calls
        self.calls += 1
        self.points.append((lat, lon))
        if self.gate is not None:
            await self.gate.wait()
        if index >= len(self._outcomes):
            raise AssertionError("FakeProvider has no outcome left for this call")
        outcome = self._outcomes[index]
        if callable(outcome):
            outcome = outcome(lat, lon)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        return outcome  # type: ignore[return-value]
