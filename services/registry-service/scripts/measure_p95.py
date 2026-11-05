"""Measure p95 latency of the read routes against a running registry-service.

Start the service first, for example: uv run uvicorn main:app
"""

import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE_URL = "http://127.0.0.1:8000"
RATE_PER_SECOND = 10
DURATION_SECONDS = 120
P95_LIMIT_MS = 100
MAX_WORKERS = 50

ROUTES = [
    "/v1/farms",
    "/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
    "/v1/plots",
    "/v1/plots/c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
    "/v1/crops",
    "/v1/crops/tomato",
    "/v1/soils",
    "/v1/soils/loam",
    "/v1/emitters",
    "/v1/emitters/dripnet-pc-1.0",
]


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def send(client: httpx.Client, route: str) -> tuple[str, int, float]:
    start = time.perf_counter()
    try:
        status = client.get(route).status_code
    except httpx.HTTPError:
        status = 0  # no response at all, so it counts as not 200
    elapsed_ms = (time.perf_counter() - start) * 1000
    return route, status, elapsed_ms


def main() -> int:
    with httpx.Client(base_url=BASE_URL) as client:
        try:
            client.get("/health").raise_for_status()
        except httpx.HTTPError:
            print(f"The server is not running at {BASE_URL}. Start it first, then run this script again.")
            return 1

        total = RATE_PER_SECOND * DURATION_SECONDS
        start = time.perf_counter()
        futures = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for i in range(total):
                # Each request starts on its own schedule, even if earlier requests are still running.
                time.sleep(max(0.0, start + i / RATE_PER_SECOND - time.perf_counter()))
                futures.append(pool.submit(send, client, ROUTES[i % len(ROUTES)]))
            results = [future.result() for future in futures]

    non_200 = sum(1 for _, status, _ in results if status != 200)
    overall = p95([ms for _, _, ms in results])

    print(f"Requests: {len(results)}")
    print(f"Not 200: {non_200}")
    print(f"p95 all routes: {overall:.1f} ms")
    for route in ROUTES:
        print(f"p95 {route}: {p95([ms for r, _, ms in results if r == route]):.1f} ms")

    return 1 if non_200 > 0 or overall > P95_LIMIT_MS else 0


if __name__ == "__main__":
    sys.exit(main())
