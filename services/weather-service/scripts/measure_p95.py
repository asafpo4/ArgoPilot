"""Measure the p95 latency of the weather service on warm cells. Not part of the service.

Warms a few cells through the service, then sends a fixed rate of requests to those cells for a fixed time.
It prints the p95 overall and per route (one route per cell), the count of non-200 answers, and whether the
fake provider saw any call during the measurement. Needs the service on 8001 and the fake provider on 9101.

Run: uv run python scripts/measure_p95.py
"""

import asyncio
import math
import sys
import time

import httpx

SERVICE = "http://127.0.0.1:8001"
FAKE = "http://127.0.0.1:9101"
RATE = 10  # requests per second
DURATION = 120  # seconds
CELLS = [("48.1", "11.6"), ("48.2", "11.6"), ("47.9", "11.4"), ("50.0", "8.5")]


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def warm(client: httpx.AsyncClient) -> None:
    for lat, lon in CELLS:
        response = await client.get(f"{SERVICE}/v1/forecast", params={"lat": lat, "lon": lon, "days": "7"})
        if response.status_code != 200:
            sys.exit(f"warm-up failed for {lat},{lon}: status {response.status_code}")


async def fake_calls(client: httpx.AsyncClient) -> int:
    response = await client.get(f"{FAKE}/calls")
    response.raise_for_status()
    return int(response.json()["calls"])


async def one(client: httpx.AsyncClient, cell: tuple[str, str], results: list[tuple[str, int, float]]) -> None:
    lat, lon = cell
    started = time.perf_counter()
    try:
        response = await client.get(f"{SERVICE}/v1/forecast", params={"lat": lat, "lon": lon, "days": "7"})
        status = response.status_code
    except httpx.HTTPError:
        status = 0  # a transport failure counts as a non-200 answer
    latency_ms = (time.perf_counter() - started) * 1000
    results.append((f"{lat},{lon}", status, latency_ms))


async def main() -> None:
    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        await warm(client)
        calls_before = await fake_calls(client)

        results: list[tuple[str, int, float]] = []
        tasks: list[asyncio.Task[None]] = []
        total = RATE * DURATION
        start = time.perf_counter()
        for i in range(total):
            delay = start + i / RATE - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            cell = CELLS[i % len(CELLS)]
            tasks.append(asyncio.create_task(one(client, cell, results)))
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        calls_after = await fake_calls(client)

    latencies = [latency for _, _, latency in results]
    non_200 = sum(1 for _, status, _ in results if status != 200)
    print(f"requests: {len(results)} in {elapsed:.1f} s (target {RATE}/s for {DURATION} s)")
    print(f"p95 overall: {p95(latencies):.1f} ms")
    for lat, lon in CELLS:
        key = f"{lat},{lon}"
        route = [latency for cell, _, latency in results if cell == key]
        print(f"p95 route {key}: {p95(route):.1f} ms (n={len(route)})")
    print(f"non-200 answers: {non_200}")
    print(f"fake provider calls during measurement: {calls_after - calls_before}")


if __name__ == "__main__":
    asyncio.run(main())
