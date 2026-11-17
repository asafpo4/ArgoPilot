# Weather service

Daily ET0 (reference evapotranspiration) and rain per 0.1° cell, from Open-Meteo, for the irrigation planner.

Weather data by [Open-Meteo.com](https://open-meteo.com/). The data is licensed CC BY 4.0, so any frontend that shows it next to a location must show the same credit with the link. The response field `source: "open-meteo"` marks such data.

## Run

```
cp .env.example .env     # the example points at the free API; add a key only for a paid plan
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1
```

Always **one worker**: the cache and the cool-down live in the memory of one process. A missing or invalid setting stops startup with an error that names the variable and the rule, never a value.

## API

`GET /v1/forecast?lat={lat}&lon={lon}&days={days}`: all three parameters are required, exactly once each; other parameters are ignored. `days` is one digit from 1 to 7. `lat` (-90 to 90) and `lon` (-180 to 180) are plain ASCII decimal numbers of at most 32 characters, with an optional exponent of up to three digits (`.5` and `5.` are rejected). A bad request is a 422 `VALIDATION` and never reaches the provider.

```json
{"lat": 31.25, "lon": 34.79, "source": "open-meteo", "fetched_at": "2026-11-16T09:30:12Z", "stale": false,
 "days": [{"date": "2026-11-16", "et0_mm": 3.1, "rain_mm": 0.0}]}
```

- `lat` and `lon` are the caller's values. The forecast is for the 0.1° cell that contains the point (the nearest 0.1° node, exact decimal rounding, ties round up). **Only that 0.1° position is sent to the provider**, never the exact coordinates.
- `date` is the local date at the point.
- **A fresh answer has exactly `days` rows. A stale answer may have fewer. A caller must check how many rows it received** and plan only those days, never filling a gap with zeros or defaults.
- `rain_mm` is Open-Meteo's `precipitation_sum`: rain, showers and snowfall together, with snow counted as water.
- Errors are `application/problem+json` (`type`, `title`, `status`, `detail`, `code`): 422 `VALIDATION`, 404 `NOT_FOUND`, 405 `VALIDATION`, 503 `UNAVAILABLE` with `Retry-After` (whole seconds, at least 1), and 500 `UNAVAILABLE` (no `Retry-After`; the real error is never sent).
- `GET /health` returns `{"status": "ok"}`. It never calls the provider and never reads the cache.

## What "today" means

Today is the local date at the point, taken from the time zone the provider reports. A cached forecast is **fresh** only while it is under `FRESH_FOR_SECONDS` old **and** its first row is today at the point, so at local midnight a cell is fetched again even if its data is minutes old. A row dated before today is never served.

## Stale answers

If a refresh fails, the old forecast is served with `stale: true` and its own `fetched_at`, as long as it is under `STALE_MAX_AGE_SECONDS` old (24 hours) and still holds a row dated today or later. Otherwise the answer is a 503.

Why 24 hours: a stale answer usually crosses one local midnight and loses one row, so a request for up to 6 days is usually complete. A daylight-saving shift near midnight can make a local day 23 hours long, and then a stale answer can cross two midnights and lose two rows. So a request for up to 5 days is always complete, 6 days usually, and 7 days only while no midnight has passed. The "today" row of a forecast older than a day is a guess made at least two days ahead, and for irrigation a clear 503, with the caller falling back to its own logic, is safer than yesterday's guess. The cap is a setting.

## Settings

Read from the environment and from `.env` next to `config.py`. A real environment variable wins over `.env`, even an empty one. An empty number is invalid.

| Variable | Default | Rule |
|---|---|---|
| `PROVIDER_BASE_URL` | none, required | `http://` or `https://` URL of the forecast endpoint |
| `PROVIDER_API_KEY` | empty | optional secret; surrounding spaces are removed |
| `PROVIDER_TIMEOUT_SECONDS` | 3 | above 0, at most 30 |
| `PROVIDER_RETRIES` | 2 | whole number 0 to 5 |
| `PROVIDER_RETRY_DELAY_SECONDS` | 0.5 | 0 to 10 |
| `FRESH_FOR_SECONDS` | 10800 (3 h) | above 0 |
| `STALE_MAX_AGE_SECONDS` | 86400 (24 h) | not below `FRESH_FOR_SECONDS` |
| `COOLDOWN_SECONDS` | 30 | 0 or more (0 turns it off) |
| `CACHE_MAX_CELLS` | 2000 | whole number, 1 or more |

**A non-empty key needs `https://`.** The key travels in the query string, so over plain `http` anyone on the network could read it. The only exception is a host that is exactly `localhost`, `127.0.0.1` or `::1`, for local fakes. The key is never logged or shown: the settings hide it, the `httpx` loggers are at WARNING, and only failure kinds are logged.

## Waiting and failing

A fetch cycle makes up to `1 + PROVIDER_RETRIES` attempts. Each attempt has a hard total deadline of `PROVIDER_TIMEOUT_SECONDS` (pool wait and connect included), with `PROVIDER_RETRY_DELAY_SECONDS` between attempts. Every failure is retried, 4xx included. A thrown error inside an attempt counts as a failed attempt.

Worst-case wait: `(PROVIDER_RETRIES + 1) × PROVIDER_TIMEOUT_SECONDS + PROVIDER_RETRIES × PROVIDER_RETRY_DELAY_SECONDS`, which is **10 s with the defaults** (3 × 3 + 2 × 0.5) and **230 s with the largest allowed values** (6 × 30 + 5 × 10).

- One cycle per cell at a time. A request that **joins a running cycle waits up to the worst case, even when a usable stale forecast exists**, because the retries come first. All waiters share the one result.
- **Cool-down:** after a failed cycle the cell does not call the provider for `COOLDOWN_SECONDS`. Requests answer at once, with the stale rows or a 503 whose `Retry-After` is the remaining cool-down. The **first request after a failure pays the full worst-case wait**; the rest are fast. A recovered provider is noticed up to 30 s late. There is no global circuit breaker.
- **Cache cap:** at most `CACHE_MAX_CELLS` cells, the least recently used goes first, and a cell with a fetch in flight is never evicted. An evicted cell loses its forecast and its cool-down. This bounds memory to a few MB. It does **not** limit provider calls: there is no per-client rate limiting, and a scan over many new coordinates costs one provider call per new cell, in parallel.

## Open-Meteo limits and terms

Checked on 2026-11-16 on open-meteo.com/en/pricing and /en/terms. The free API allows fewer than 10,000 calls per day, 5,000 per hour and 600 per minute (300,000 per month), counted by IP address and application, with no uptime guarantee. It is **for non-commercial use only** (the terms say what counts), and Open-Meteo may block applications that misuse it. Commercial use needs a paid plan: put its key in `PROVIDER_API_KEY` and the plan's host (`customer-api.open-meteo.com`) in `PROVIDER_BASE_URL`.

The cache is why the service fits inside these limits: a cell requested all day costs at most about 9 successful fetches a day (one every 3 hours, plus the refresh at local midnight). A scan over many new cells can exceed them, and the provider then answers with errors. Every failed attempt is retried and counts against the limit (up to 3 calls per failed cycle by default).

## Tests and measurement

```
uv run pytest -q -p no:cacheprovider                                   # default suite; no network
RUN_REAL_PROVIDER_TEST=1 uv run pytest tests/test_real_provider.py -v  # optional smoke test: one real provider call
```

The smoke test is skipped in the default run.

p95 measurement (NFR-2.3), with a local fake provider so no real call is made:

```
uv run python scripts/fake_provider.py                                  # 127.0.0.1:9101, call count at /calls
PROVIDER_BASE_URL=http://127.0.0.1:9101/v1/forecast PROVIDER_API_KEY= \
  uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1
uv run python scripts/measure_p95.py
```

Measured on 2026-11-17, on a WSL2 Linux machine, one worker, four warm cells, 10 requests per second for 120 s (1200 requests, `days=7`), the fake provider on localhost:

| | |
|---|---|
| p95 overall | **10.4 ms** |
| p95 per cell | 10.1 to 10.5 ms (300 requests each) |
| non-200 answers | 0 |
| provider calls during the measurement | 0 |
