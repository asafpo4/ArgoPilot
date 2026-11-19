"""The clock every time-dependent rule uses. Tests replace it with a fake clock."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, UTC and timezone-aware. Used for "today" and fetched_at."""
        ...

    def monotonic(self) -> float:
        """A clock that never goes back. Used for ages and cool-downs."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait, through the clock, so a fake clock can move time at once."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
