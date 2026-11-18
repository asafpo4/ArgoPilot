"""The real sleep. Tests pass a fake one to the upstream client instead."""

import asyncio


async def real_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
