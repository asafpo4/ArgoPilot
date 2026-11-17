"""The forecast service: freshness, stale rules and the fetch cycle (spec 3.2 to 3.5).

Requests for one cell share one fetch cycle (single flight). It logs failure kinds only: never a URL, a body or an
exception message.
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from clock import Clock
from config import Settings
from grid import Cell, node_for
from provider import Day, Failure, Provider, ProviderForecast

logger = logging.getLogger("weather.service")


@dataclass(frozen=True)
class ForecastResult:
    kind: Literal["fresh", "stale", "unavailable"]
    fetched_at: datetime | None = None
    rows: tuple[Day, ...] = ()
    retry_after: int | None = None


@dataclass(frozen=True)
class _Stored:
    forecast: ProviderForecast
    fetched_at: datetime  # UTC wall time, for the response.
    fetched_mono: float  # For ages.


@dataclass
class _Entry:
    stored: _Stored | None = None
    cooldown_end: float | None = None
    inflight: "asyncio.Task[bool] | None" = None  # The running fetch cycle of this cell.


@dataclass
class ForecastService:
    provider: Provider
    clock: Clock
    settings: Settings
    _entries: dict[Cell, _Entry] = field(default_factory=dict, init=False)

    async def get(self, cell: Cell, days: int) -> ForecastResult:
        entry = self._entries.setdefault(cell, _Entry())
        if entry.stored is not None and self._is_fresh(entry.stored):
            return ForecastResult("fresh", entry.stored.fetched_at, entry.stored.forecast.rows[:days])
        # No await from the check of the marker to its storing: two requests never both start a fetch.
        task = entry.inflight
        if task is None:
            task = asyncio.create_task(self._run_cycle(cell, entry))
            entry.inflight = task
        # The shield keeps a cancelled waiter from cancelling the fetch for the others.
        if await asyncio.shield(task):
            assert entry.stored is not None
            return ForecastResult("fresh", entry.stored.fetched_at, entry.stored.forecast.rows[:days])
        return self._failure_answer(entry, days)

    async def aclose(self) -> None:
        """Cancel the running fetch cycles and clear their markers."""
        running = [(e, e.inflight) for e in self._entries.values() if e.inflight is not None]
        for _, task in running:
            task.cancel()
        await asyncio.gather(*(task for _, task in running), return_exceptions=True)
        for entry, task in running:
            if entry.inflight is task:  # A task cancelled before it started never ran its `finally`.
                entry.inflight = None

    async def _run_cycle(self, cell: Cell, entry: _Entry) -> bool:
        """The cycle as a task: it ends with True or False and never raises to the waiters."""
        task = asyncio.current_task()
        try:
            return await self._fetch_cycle(cell, entry)
        except Exception as exc:  # Only the class is logged, never the message.
            entry.cooldown_end = self.clock.monotonic() + self.settings.COOLDOWN_SECONDS
            logger.warning(
                "provider cycle failed: cell=%s,%s kinds=unexpected %s",
                cell.lat_index, cell.lon_index, type(exc).__name__,
            )
            return False
        finally:
            if entry.inflight is task:
                entry.inflight = None

    def _today(self, stored: _Stored):
        return self.clock.now().astimezone(stored.forecast.tz).date()

    def _age(self, stored: _Stored) -> float:
        return self.clock.monotonic() - stored.fetched_mono

    def _is_fresh(self, stored: _Stored) -> bool:
        return (
            self._age(stored) < self.settings.FRESH_FOR_SECONDS
            and stored.forecast.rows[0].date == self._today(stored)
        )

    def _usable_stale_rows(self, stored: _Stored, days: int) -> tuple[Day, ...]:
        """The rows dated today or later (at most `days`); empty when the forecast is not usable."""
        if self._age(stored) >= self.settings.STALE_MAX_AGE_SECONDS:
            return ()
        today = self._today(stored)
        return tuple(row for row in stored.forecast.rows if row.date >= today)[:days]

    def _failure_answer(self, entry: _Entry, days: int) -> ForecastResult:
        if entry.stored is not None:
            rows = self._usable_stale_rows(entry.stored, days)
            if rows:
                return ForecastResult("stale", entry.stored.fetched_at, rows)
        remaining = (entry.cooldown_end or 0.0) - self.clock.monotonic()
        return ForecastResult("unavailable", retry_after=max(1, math.ceil(remaining)))

    async def _fetch_cycle(self, cell: Cell, entry: _Entry) -> bool:
        """Up to 1 + retries attempts, a delay between them. True when a forecast was stored."""
        lat, lon = node_for(cell)
        attempts = 1 + self.settings.PROVIDER_RETRIES
        kinds: list[str] = []
        for attempt in range(1, attempts + 1):
            try:
                outcome = await self.provider.fetch(lat, lon)
            except Exception as exc:  # An unexpected error is a failed attempt; only its class is logged.
                outcome = Failure("unexpected " + type(exc).__name__)
            if isinstance(outcome, ProviderForecast):
                entry.stored = _Stored(outcome, self.clock.now(), self.clock.monotonic())
                entry.cooldown_end = None
                return True
            kinds.append(outcome.kind)
            logger.warning("provider attempt failed: cell=%s,%s attempt=%d kind=%s", cell.lat_index, cell.lon_index, attempt, outcome.kind)
            if attempt < attempts:
                await self.clock.sleep(self.settings.PROVIDER_RETRY_DELAY_SECONDS)
        entry.cooldown_end = self.clock.monotonic() + self.settings.COOLDOWN_SECONDS
        logger.warning("provider cycle failed: cell=%s,%s kinds=%s", cell.lat_index, cell.lon_index, ",".join(kinds))
        return False
