"""The optional smoke test: one real call to the public Open-Meteo endpoint, with the real clock.

Skipped unless RUN_REAL_PROVIDER_TEST=1, so the default suite never leaves the machine.
"""

import os
from decimal import Decimal

import httpx
import pytest

from clock import SystemClock
from provider import OpenMeteoProvider, ProviderForecast

REAL_URL = "https://api.open-meteo.com/v1/forecast"


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_PROVIDER_TEST") != "1",
    reason="set RUN_REAL_PROVIDER_TEST=1 to make one real provider call",
)
@pytest.mark.anyio
async def test_the_real_provider_answer_passes_every_rule() -> None:
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoProvider(
            client, base_url=REAL_URL, api_key="", timeout=10.0, clock=SystemClock()
        )
        result = await provider.fetch(Decimal("48.1"), Decimal("11.6"))
    assert isinstance(result, ProviderForecast), f"expected a forecast, got {result!r}"
    assert len(result.rows) == 7
