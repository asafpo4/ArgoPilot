# Weather service: design

Status: approved by the user on 2026-11-16 (after review in five parts). Branch: `p2`. Date: 2026-11-16.
Part of task P2. The registry-service part is finished; this service shares no code with it.
Decisions already in `docs/judgment-log.md`: entry 1 (what "today" means) and entry 2 (a stale answer may have fewer rows). More entries are added with the plan.

---

# Part 1. Intent and scope

## 1.1 What this is and why

`weather-service` answers one question: for a point on Earth, what are the daily ET0 (reference evapotranspiration) and rain for the next days, starting today? Later, a planner-service will use the answer to decide how much water a plot needs. The service knows coordinates and dates only. It knows nothing about farms, plots or crops.

The weather comes from Open-Meteo. The service sits between the callers and the provider for four reasons: it limits calls to the provider (one forecast per 0.1° cell, reused for 3 hours), it keeps working through short provider failures (retries, then the last forecast, marked stale), it hides the provider's field names from every caller, and it never makes a number up.

The last point is the reason the design is strict. A forecast of zeros reads as "no rain, no water needed". It is the worst bug this system can have, so every rule below prefers an honest "no answer" (503) or a shorter answer over a plausible invented one.

## 1.2 Requirements and where they are handled

| Requirement | Where |
|---|---|
| FR-2.3 `GET /v1/forecast?lat&lon&days`: date, ET0 mm, rain mm, for each of the next `days` days starting today | 2.1, 2.2, 3.4 |
| FR-2.4 lat -90..90, lon -180..180, days 1..7, otherwise 422 `VALIDATION` | 2.1, 2.3 |
| FR-2.5 same 0.1° cell shares one forecast; fresh for 3 hours; no provider call while fresh | 3.1 to 3.4 |
| FR-2.6 on provider failure retry twice, then answer with the last forecast, `stale: true` | 3.5, 3.4 |
| FR-2.7 failure and no earlier forecast: 503 `UNAVAILABLE` with `Retry-After` | 3.4, 2.3 |
| FR-2.8 never answer with numbers the provider did not give | 4.2, 5.3 |
| NFR-2.3 fresh answer: p95 <= 100 ms at 10 requests per second | 5.4 |

## 1.3 Goals, non-goals, anti-goals

Goals
- Every number in a 200 answer was given by the provider, unchanged.
- Every row's date is the provider's date, and the first row of a fresh answer is today at the point (entry 1).
- A provider outage costs callers at most one documented slow answer per cell per cool-down period.
- Concurrent requests for the same cell cause one provider call. The others wait and share its result, including a failure, within the documented bounded wait (3.5; judgment log, the entry on one fetch per cell, added with the plan).
- Memory is bounded. The provider is not hammered, by one caller or by many.
- Settings come from `.env` through pydantic-settings in one `config.py`. A missing required variable stops startup with a clear error.

Non-goals
- No database and no files: the cache lives in the memory of one process, and a restart empties it.
- No per-client rate limiting. A caller that walks through coordinates costs one provider call per new cell. This is written in the README.
- No coordination between processes: the service must run with a single worker (README).
- No hourly data, no other variables, no past days, no second provider. Only `provider.py` would change for those.
- No proactive refresh of cells in the background.
- No global (whole-provider) circuit breaker. The cool-down is per cell (judgment log, later entry).
- No metrics endpoint. No authentication.

Anti-goals (a failure even if the tests pass)
- A 200 answer that holds a zero, a default, an interpolated or a converted number the provider did not give.
- A row labeled with a date that is not the provider's date for that row, or a first row that is not today at the point.
- The API key, or a URL that carries it, in any log line, error message, `repr` or printed traceback, including through the exception chain.
- A request that waits longer than the documented worst case.
- Code that imports from `services/registry-service`, or Open-Meteo's field names outside `provider.py` and the fakes that imitate the provider.

## 1.4 Constraints from the task

- Python 3.12, FastAPI, uvicorn, uv, pydantic-settings, like the registry. Own `.venv`, `.env`, `.env.example`, `README.md`, `config.py`, `tests/`.
- The provider is called with `httpx`. Base URL, timeout, number of retries and freshness time are in `.env`. An API key variable exists and may be empty.
- Errors are `application/problem+json` with the codes `VALIDATION` (422), `NOT_FOUND` (404), `UNAVAILABLE` (503, with `Retry-After`), in the registry's style.
- `.env.example` is committed with placeholders only. `.env` is never committed (the root `.gitignore` already ignores it).
- The README states how old a forecast may get before it is not served even as stale, and why (24 hours: a stale answer usually crosses one midnight and loses one row, and a daylight-saving shift near midnight can cost two; see 3.3).
- Open-Meteo's free API is for non-commercial use, has call limits, and its data is licensed CC BY 4.0, which requires credit (4.1, 5.5, 5.6).

---

# Part 2. The API

## 2.1 Request

`GET /v1/forecast?lat={lat}&lon={lon}&days={days}`

All three parameters are required and must appear exactly once (a repeated parameter is found from the raw query string, because a framework's single-value parameter would hide it). Other query parameters are ignored. The accepted text is exact:

| Parameter | Accepted text | Range |
|---|---|---|
| `days` | exactly one ASCII digit, `1` to `7`. No sign, no spaces, no leading zero, no non-ASCII digit | 1 to 7 |
| `lat` | ASCII only, at most 32 characters, matching `[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?`: an optional sign, digits, an optional decimal part (a dot and digits), and an optional exponent (`e` or `E`, an optional sign, one to three digits). A caller written in Python may send `1e-05` | -90 to 90 inclusive |
| `lon` | the same text rules as `lat` | -180 to 180 inclusive |

How the check works:
- The text is checked against these patterns first, and only then the value. Either failure returns 422 with code `VALIDATION`.
- The range is checked on the exact decimal value of the text, so `90.0000000000000001` is out of range and is not rounded to `90`.
- The service must not hand the raw text to `float()` or `int()` to decide whether it is valid: Python accepts `1_0`, non-ASCII digits, spaces, `nan` and `inf` there.
- The exponent is limited to three digits in the pattern because Python's `Decimal` raises `InvalidOperation` for an exponent beyond its limits (checked: `Decimal('1e99999999999999999999999')` and `Decimal('1e-99999999999999999999999')` both do), which would be a 500. As a second line of defence, any error from converting the text to a decimal also returns 422 `VALIDATION`.
- The cell (3.1) is computed from the decimal text of the accepted value, never from a float. A float is made only to echo `lat` and `lon` in the response.
- The check happens before the cache or the provider is touched, so an invalid request never causes a provider call.

One test case per row of this table (parametrized), and each rejected case must return problem+json `VALIDATION`:

| Parameter | Accepted | Rejected |
|---|---|---|
| `days` | `1`, `2`, `3`, `4`, `5`, `6`, `7` | `0`, `8`, `9`, `10`, `07`, `+3`, `-3`, ` 3`, `3 `, `3.0`, `3.5`, `3e0`, `٣` (Arabic-Indic digit), `３` (full-width digit), empty, missing, repeated (`days=1&days=2`) |
| `lat` | `0`, `-0`, `+0`, `31.25`, `+31.25`, `-90`, `90`, `90.0`, `-89.9999`, `1e-05`, `1E-5`, `-1.5e1`, `9e0`, `1e-999` | `90.0000000000000001`, `-90.1`, `91`, `1e2`, `1e999` (valid text, out of range), `1e1000`, `1e-1000` (exponent of four digits), `1e9999999999999999999999999` and `1e-9999999999999999999999999` (an exponent of 25 digits), `1_0`, ` 1`, `1 `, `0x1A`, `nan`, `NaN`, `inf`, `-inf`, `infinity`, `١٢` (Arabic-Indic digits), `１２` (full-width digits), `.5`, `5.`, `1e`, `1e+`, `--1`, `1.2.3`, `1,5`, empty, a 33-character number, missing, repeated |
| `lon` | `0`, `-180`, `180`, `180.0`, `-179.99`, `+34.79`, `1e-05`, `1.8e2`, `1e-999` | `180.0000000000001`, `-180.1`, `181`, `1e3`, `1e1000`, `1e-1000`, `1e9999999999999999999999999` and `1e-9999999999999999999999999` (an exponent of 25 digits), `1_0`, ` 1`, `1 `, `0x1A`, `nan`, `inf`, `-inf`, `１２`, `.5`, `5.`, empty, missing, repeated |

`.5` and `5.` are rejected on purpose: the pattern asks for digits on both sides of the dot.

## 2.2 Response (200)

```json
{
  "lat": 31.25,
  "lon": 34.79,
  "source": "open-meteo",
  "fetched_at": "2026-11-16T09:30:12Z",
  "stale": false,
  "days": [
    {"date": "2026-11-16", "et0_mm": 3.1, "rain_mm": 0.0},
    {"date": "2026-11-17", "et0_mm": 2.9, "rain_mm": 1.4}
  ]
}
```

- `lat`, `lon`: the values the caller sent, unchanged. The forecast applies to the 0.1° cell that contains the point (3.1).
- `source`: always `"open-meteo"`.
- `fetched_at`: the time our service received the forecast from the provider, in UTC, ISO 8601 with a trailing `Z`, to the second. For a stale answer it is the time of the stale forecast, so the caller can see its age.
- `stale`: `false` for a forecast that is fresh now, `true` when the answer comes from an older forecast because the provider could not be used (3.4).
- `days`: dated rows in date order. `date` is a local date at the point (`YYYY-MM-DD`), exactly as the provider gave it. `et0_mm` and `rain_mm` are the provider's numbers, unchanged and unrounded. **A fresh answer has exactly `days` rows. A stale answer has the rows dated today or later that the old forecast still holds, at most `days`, so it may have fewer (entry 2). A caller must check how many rows it received.**
- No other fields. The names of the provider's fields never appear.

A stale answer is never an empty list. If no row dated today or later is left in the old forecast, the answer is a 503 (3.3).

`rain_mm` is the provider's daily `precipitation_sum`, in mm. The field name stays `rain_mm` because the task fixes it. Open-Meteo documents the value as rain, showers and snowfall together, with snow counted as water. That is the number that matters for irrigation, and the README says that it includes showers and snow counted as water.

## 2.3 Errors

All errors are `application/problem+json` with `type`, `title`, `status`, `detail` and `code`, built the way `services/registry-service/errors.py` builds them (this service has its own copy; it imports nothing from the registry).

| Case | Status | `code` | Notes |
|---|---|---|---|
| Invalid or missing parameter | 422 | `VALIDATION` | title "Unprocessable Entity"; detail lists each `field: message` |
| Unknown route | 404 | `NOT_FOUND` | |
| Method not allowed | 405 | `VALIDATION` | same choice as registry entry 5 |
| No usable forecast, provider failing | 503 | `UNAVAILABLE` | header `Retry-After`: whole seconds, the remaining cool-down rounded up, at least 1 |
| Unexpected server error | 500 | `UNAVAILABLE` | no `Retry-After`, same choice as registry entry 14; the real error is never sent |

The detail of a 503 is a fixed text (`Forecast unavailable`). It never carries anything from the provider. A stale 200 answer has no `Retry-After`.

## 2.4 Health

`GET /health` returns `{"status": "ok"}`. It never calls the provider and never reads the cache, so a health check cannot use up the provider's quota or be slowed by it.

---

# Part 3. Forecast rules

## 3.1 Cells

Two points share a forecast when they have the same cell. The cell is the point rounded to the nearest 0.1°: for each coordinate, `index = floor(value × 10 + 0.5)` (ties round up), computed on the decimal text of the accepted value (2.1) with exact decimal arithmetic, never from a float, so that float noise cannot change the cell (`0.3` is index 3, not 2). The arithmetic must really be exact: Python's default `Decimal` precision is 28 digits, and with it the 32-character text `0.049999999999999999999999999999`, which is just below the tie, comes out as index 1 instead of 0 (checked). Use a decimal context whose precision covers the longest accepted text (32 characters with an exponent of up to ±999 needs about 1100 digits, so 2100 is safe), or exact fractions. The cell key is `(lat_index, lon_index)`. Indexes stay within ±900 and ±1800, so no cell is outside the valid range. Examples: `31.25` is index 313 (node 31.3), `-0.05` is index 0, `90` is index 900, `-180` and `180` are different cells (-1800 and 1800), and that is accepted.

The provider is called at the cell's node (one decimal, for example `31.3`, `34.8`), never at the caller's exact point. This makes the cached forecast the same no matter which caller asked first, and it means only a 0.1° position leaves the service, not the exact coordinates.

## 3.2 What is kept for a cell

An entry holds: the stored forecast (or none), a cool-down end time (or none), and the fetch in flight (or none).

A stored forecast holds: `fetched_at` (UTC wall time, for the response), the monotonic time of the fetch (for ages), the point's time zone (rules in 4.2 and 4.5), and exactly 7 rows `(date, et0_mm, rain_mm)` as validated in 4.2.

The cache is an ordered map from cell key to entry (3.6).

## 3.3 Fresh, stale, usable

Let `now` come from the injected clock (4.5), and `today` be the date of `now` in the stored forecast's time zone.

- **Fresh:** age < `FRESH_FOR_SECONDS` (default 3 hours) **and** the first row's date is `today` (entry 1).
- **Usable as stale:** age < `STALE_MAX_AGE_SECONDS` (default 24 hours) **and** at least one row is dated `today` or later. The rows served are those dated `today` or later, at most `days`. A stale answer is therefore never an empty list: with no such row the forecast is not usable and the answer is a 503.
- A row dated before `today` is never served.

Why 24 hours (the README repeats this, in these words): a stale answer usually crosses one local midnight and loses one row, so a request for up to 6 days is usually complete. A daylight-saving shift near midnight can make a local day 23 hours long, and then a stale answer can cross two midnights and lose two rows. So a request for up to 5 days is always complete, 6 days usually, and 7 days only while no midnight has passed. The "today" row of a forecast older than a day is a guess made at least two days ahead, and for irrigation a clear 503, with the caller falling back to its own logic, is safer than yesterday's guess. The cap is a setting.

## 3.4 What one request does

After validation (2.1) the request finds or creates its cell's entry, marks it most recently used, and then, in this order:

1. **Fresh forecast:** return it (`stale: false`). No provider call.
2. **A fetch for this cell is in flight:** wait for it (3.5).
   - It succeeded: return the new forecast (`stale: false`).
   - It failed: go to step 5.
3. **Cool-down active** (`monotonic < cooldown_end`): go to step 5 at once, with no provider call and no wait.
4. **Otherwise start a fetch** (3.5) and wait for it, as in step 2.
5. **Failure answer:** if the entry's forecast is usable as stale (3.3), return it with `stale: true` and its own `fetched_at`. Otherwise return 503 with `Retry-After` = remaining cool-down rounded up to whole seconds, at least 1.

Every outcome of a fetch is shared by all requests waiting on it. Nobody who waited starts a second fetch of their own. Steps 1 to 4, up to the moment the fetch task is created and stored as the in-flight marker, run without an `await` in between, so two requests can never both start a fetch for the same cell.

## 3.5 The fetch cycle

One cycle runs as its own task, so a waiting caller that disconnects does not cancel it for the others (waiters wait on the task through a shield). The task never raises to its waiters: it ends with a success value or a failure value. Waiting requests all receive the same value. At shutdown the service cancels running tasks.

The cell's in-flight marker is cleared in a `finally` block, whatever happens: success, a failed cycle, an unexpected exception, or cancellation. An unexpected exception is logged without secrets (the exception class only, never its message) and counts as a failed cycle, so the cool-down starts. Without the `finally`, the cell would wait forever on a task that is gone, and could never be evicted (3.6).

A cycle makes up to `1 + PROVIDER_RETRIES` attempts (default 3).
- Each attempt has a hard total deadline of `PROVIDER_TIMEOUT_SECONDS` (default 3 s) for the whole exchange, from the request to the last byte of the body. It is not only an idle timeout, so a provider that sends one byte at a time cannot stretch the wait. The deadline also covers waiting for a free connection in the shared client, and connecting. The cycle applies it around the whole call itself and does not leave it to httpx's per-phase timeouts, so a full connection pool cannot stretch the wait either, and the worst case below holds under load.
- An attempt fails on any condition in 4.2, on a transport error, on the deadline, and on any HTTP status other than 200.
- Between attempts the cycle waits `PROVIDER_RETRY_DELAY_SECONDS` (default 0.5 s), through the injected clock. There is no wait after the last attempt.
- All failures are retried, including HTTP 4xx, because FR-2.6 says so. A 4xx means our request is wrong and retrying will not help, so each failed attempt is logged with its status (4.4) and a bad configuration is visible.
- **Success:** validation passed (4.2), including that the first row is today at the point by our clock at the moment the response arrived. Store the forecast (replacing any older one), clear the cool-down, return success. A response whose first row is not today counts as a failure: a day roll-over during the request, or a clock that disagrees with the provider, must never produce a row labeled as today when it is not. The next attempt normally succeeds.
- **Failure of the whole cycle:** set `cooldown_end = monotonic + COOLDOWN_SECONDS` (default 30 s; 0 turns the cool-down off) and return failure. The stored forecast, if any, is kept.

Worst-case wait for a request that starts or joins a cycle: `(PROVIDER_RETRIES + 1) × PROVIDER_TIMEOUT_SECONDS + PROVIDER_RETRIES × PROVIDER_RETRY_DELAY_SECONDS`, which is 10 s with the defaults and at most 230 s with the largest values the settings allow (5 retries, a 30 s timeout, a 10 s delay). This is the longest any request can wait, and the README states the formula, the default and the maximum. A request that finds the cell in a cool-down does not wait.

## 3.6 Cache cap and eviction

- At most `CACHE_MAX_CELLS` entries (default 2000). The entries are ordered by last use; every request for a cell, fresh or not, makes it most recently used.
- When a new entry would exceed the cap, the least recently used entries are evicted until it fits, **skipping any entry with a fetch in flight**. If every entry is in flight, the cache is allowed to exceed the cap until some finish; the new entry is never evicted by its own insertion.
- Whenever a new entry is created, entries whose forecast is older than `STALE_MAX_AGE_SECONDS` and that have no fetch in flight are dropped first, because they can never be served.
- Evicting an entry forgets its forecast and its cool-down. A request for an evicted cell during an outage therefore finds nothing to serve: it starts a fetch cycle (and, if that fails, gets the 503). It is never answered with rows that were evicted.
- This bounds memory to a few MB. It does not limit how often callers can cause provider calls (non-goals).

## 3.7 What this gives the callers

| Situation | Answer | Wait |
|---|---|---|
| Fresh forecast | 200, `stale: false` | none (a dictionary lookup) |
| Cell expired, provider healthy | 200, `stale: false` | one provider call (about 0.3 s measured) |
| Provider failing, old usable forecast | 200, `stale: true`, maybe fewer rows | up to the worst case for the request that starts the cycle and for every request that joins it while it runs, then none during the cool-down |
| Provider failing, nothing usable | 503 with `Retry-After` | up to the worst case for the request that starts the cycle and for every request that joins it while it runs, then none during the cool-down |

---

# Part 4. The provider and settings

## 4.1 The Open-Meteo call

`provider.py` is the only code that knows Open-Meteo's names. One `GET` to `PROVIDER_BASE_URL` (the full forecast endpoint, for example `https://api.open-meteo.com/v1/forecast`) with the query:

`latitude`, `longitude` (the cell node), `daily=et0_fao_evapotranspiration,precipitation_sum`, `forecast_days=7`, `timezone=auto`, and `apikey` only when `PROVIDER_API_KEY` is not empty.

Checked on 2026-11-16 against the docs and a live call: `forecast_days` allows up to 16, so 7 is fine. With `timezone=auto` the daily `time` values are local dates at the point (`YYYY-MM-DD`), and the response carries `timezone` (an IANA name such as `Europe/Berlin`) and `utc_offset_seconds`. Both daily variables are in mm, and `daily_units` says so. An invalid request returns HTTP 400 with `{"error": true, "reason": …}`. The docs page does **not** say whether a daily value can be `null`, so the service treats `null` as a missing field. The free API has limits, stated on open-meteo.com/en/pricing and /en/terms (checked 2026-11-16): fewer than 10,000 calls per day, 5,000 per hour and 600 per minute (300,000 per month in the comparison table), counted by IP address and application, with no uptime guarantee. It is for non-commercial use only, and Open-Meteo reserves the right to block applications and IP addresses that misuse it. The design keeps calls low (3.1 to 3.6) but does not enforce these limits.

The service always asks for 7 days and serves the first `days`, so every request in a cell shares one forecast. Redirects are not followed (a redirect would send the key to another host); a redirect status is a failure. TLS verification stays on. One shared `httpx.AsyncClient` is created at startup and closed at shutdown. The per-attempt deadline of 3.5 covers the whole call, including waiting for a free connection in this shared client, so the 10 s worst case holds under load.

## 4.2 What counts as a failure (FR-2.8)

The provider's answer is accepted only if all of this holds. Otherwise the attempt fails and nothing from it is stored or served.

- HTTP status 200, and the body is JSON, and the JSON is an object.
- `daily` is an object holding `time`, the ET0 array and the precipitation array, each a list of exactly **7** entries.
- `daily_units` says `mm` for both variables.
- Every `time` entry is a valid `YYYY-MM-DD` date, the dates are consecutive, and the first one is today at the point (3.5).
- Every ET0 and precipitation entry is a real number (an integer or a float, not a boolean, not a string, not `null`), finite, and not negative.
- The time zone is known: `timezone` is an IANA name that `zoneinfo` knows. If not, `utc_offset_seconds` is used as a fixed offset if it is a whole number within ±18 hours. If neither works, the attempt fails.

A single bad entry rejects the whole response. There is no partial use, no zero for a missing value and no default for a missing day. Extra fields in the response are ignored.

## 4.3 Settings (`.env`, read by pydantic-settings in `config.py`)

| Variable | Default | Rule |
|---|---|---|
| `PROVIDER_BASE_URL` | none, **required** | an `http://` or `https://` URL; with a non-empty `PROVIDER_API_KEY` it must be `https://`, except for a local host (below) |
| `PROVIDER_API_KEY` | empty | optional; a secret; leading and trailing spaces are removed, and a value of only spaces counts as empty |
| `PROVIDER_TIMEOUT_SECONDS` | 3 | number > 0 and <= 30 |
| `PROVIDER_RETRIES` | 2 | whole number 0 to 5 |
| `PROVIDER_RETRY_DELAY_SECONDS` | 0.5 | number 0 to 10 |
| `FRESH_FOR_SECONDS` | 10800 (3 h) | number > 0 |
| `STALE_MAX_AGE_SECONDS` | 86400 (24 h) | number >= `FRESH_FOR_SECONDS` |
| `COOLDOWN_SECONDS` | 30 | number >= 0 (0 = off) |
| `CACHE_MAX_CELLS` | 2000 | whole number >= 1 |

- `PROVIDER_BASE_URL` has no default on purpose: a missing `.env` must stop the service, not silently call the internet. This is where the service demonstrates the "missing required variable stops startup" rule.
- The `.env` file is found next to `config.py`, not in the working directory. A real environment variable wins over `.env`, even an empty one.
- **The key needs https.** If `PROVIDER_API_KEY` is not empty, `PROVIDER_BASE_URL` must use `https://`. The only exception is a host that is exactly `localhost`, `127.0.0.1` or `::1`, so that local fakes work. The reason: the key travels in the query string, and over plain `http` anyone on the network can read it. The host is the one `urlsplit` reads from the URL (so `localhost.example.com`, `127.0.0.1.example.com` and `http://localhost@example.com` are not local), compared case-insensitively. Startup fails like any other bad variable: the error names `PROVIDER_BASE_URL` and the rule, and shows no value.
- A missing or invalid variable stops startup with a clear error that names every bad variable and the rule it broke, for example `PROVIDER_BASE_URL: required`. The error never shows a value, so it cannot show the key.
- `.env.example` is committed with every variable in this table (the stale cap, the cool-down, the cache cap and the wait bounds included), placeholders only, and a comment on each. A test checks that every setting in `Settings` appears in `.env.example`, and the other way round.
- The wait bounds are `PROVIDER_TIMEOUT_SECONDS`, `PROVIDER_RETRIES` and `PROVIDER_RETRY_DELAY_SECONDS`. Together they set the worst-case wait of 3.5, which the README states.

## 4.4 Secrets and logging

The bar is the registry's, including what its final review found.
- `PROVIDER_API_KEY` is a `SecretStr`. `repr` and `str` of the settings never show the key or the base URL.
- httpx logs request URLs at INFO, and the URL carries the key. The service sets the `httpx` and `httpcore` loggers to WARNING at startup.
- The code never formats a provider URL, a request, a response body or an `httpx` exception message into a log line or an error. It logs failure kinds only.
- Translated failures are raised after their `except` block ends, so no httpx exception (whose message can hold the URL) stays in `__context__` of anything that escapes.
- One WARNING per failed attempt: cell node, attempt number, and a kind: `timeout`, `transport`, `status <code>`, `not_json`, or `invalid` plus which rule of 4.2 failed. One WARNING when a cycle ends in failure and a cool-down starts. Nothing else is logged on the request path.

## 4.5 Time

All time comes from an injected `Clock` with three methods: `now()` (UTC, timezone-aware), `monotonic()` and `sleep(seconds)` (async). Production uses the real ones. Tests use a fake clock that moves `now()` and `monotonic()` together and whose `sleep` advances them at once. Ages and cool-downs use `monotonic()`; "today" and `fetched_at` use `now()`. The per-attempt deadline of 3.5 uses the event loop's real time, so its tests use a very small timeout.

---

# Part 5. Build and test

## 5.1 Approaches considered

- **A. Async FastAPI with one forecast service that owns the rules (chosen).** A request that waits for a shared fetch costs a pending task, so waiting never slows fresh answers.
- **B. Plain synchronous FastAPI, threads and locks.** Rejected: every waiting request holds a thread (the pool defaults to 40). At 10 requests per second during a 10 s cycle about 100 would wait, and fresh answers would queue behind them, which breaks NFR-2.3 exactly when the provider struggles.
- **C. A background refresher that keeps requested cells warm.** Rejected: it needs a schedule per cell, spends provider calls on cells nobody asks about any more, and adds timing logic that FR-2.5 to 2.7 do not need.

## 5.2 Layout

`services/weather-service/`, flat modules like the registry.

| File | Responsibility |
|---|---|
| `main.py` | `create_app(settings=None, transport=None, clock=None)` and `app`; startup loads settings (`ConfigError` stops startup); routes `/v1/forecast`, `/health` |
| `config.py` | `Settings`, `ConfigError`, `load_settings()` |
| `errors.py` | problem+json helpers and handlers (own copy of the registry's style) |
| `schemas.py` | response models and the request validation; no defaults on any weather field |
| `grid.py` | `cell_for(lat, lon)` and `node_for(cell)` |
| `provider.py` | the Open-Meteo call and the checks of 4.2; returns a validated forecast or a failure kind |
| `forecast_service.py` | cache, freshness, single flight, cool-down, eviction (3.2 to 3.6); takes the provider and the clock as arguments |
| `clock.py` | `Clock`, the real clock |
| `scripts/measure_p95.py`, `scripts/fake_provider.py` | the NFR-2.3 measurement and a local stand-in for the provider |
| `tests/` | see 5.3 |
| `README.md`, `.env.example`, `pyproject.toml`, `uv.lock` | |

Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28` (runtime), `pydantic-settings~=2.16`, `tzdata` (so time zones work on every machine); dev: `pytest~=9.2`.

The service listens on port **8001** (the registry uses 8000, the planner 8002 in the task). The exact command, from `services/weather-service`, with one worker:

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1
```

## 5.3 Tests

No test in the default run touches the real network. The real provider client runs against `httpx.MockTransport`; time comes from the fake clock. Groups:

- **Cells:** `0.049999999999999999999999999999` is index 0 and `0.05` is index 1 (a builder who keeps the default `Decimal` precision gets 1 for both), `1e-999` is index 0, neighbours in one cell, points across a boundary, negatives, the edges (`90`, `-90`, `180`, `-180`), values like `0.3`, `0.7`, `0.1 + 0.2` (decimal text, not float noise).
- **Validation:** one parametrized case per row of the tables in 2.1, accepted and rejected, each bound and one step beyond it; every rejected case is problem+json `VALIDATION` and causes no provider call. The cases `1_0`, a non-ASCII digit, a space, `nan` and `inf` are there because plain `float()` or `int()` would accept them, so the tests catch a builder who validates with those.
- **Provider checks (4.2):** a valid body; every failure kind one by one (status, not JSON, not an object, a missing field, `null`, a string, a boolean, `NaN`, negative, 6 or 8 rows, wrong units, a bad date, a date gap, first row not today, unknown time zone with and without a usable offset, a redirect, a timeout, a transport error, and a client that blocks before connecting and never returns, as with a full connection pool). None of them may produce a 200. The blocking client must still fail the attempt inside the deadline, and a whole cycle of three attempts must end within `3 × timeout + 2 × delay` plus a small margin (use a timeout of about 0.05 s).
- **Service rules (fake provider, fake clock):** fresh answers make no provider call; expiry by age; expiry by local midnight with a farm east and west of UTC; a stale answer after the retries (3 calls); stale rows dated before today dropped and the list shorter; the 24-hour cap; no forecast gives 503 with `Retry-After`.
- **Daylight saving:** a real zone with a 23-hour day, using `tzdata`. In `Europe/Berlin` the clocks go forward on 2027-03-28, so that local day lasts 23 hours. A forecast is fetched at 2027-03-27 23:30 local (22:30 UTC), with rows `2027-03-27` to `2027-04-02`. The provider then fails, and a request arrives at 2027-03-28 22:10 UTC, which is 2027-03-29 00:10 local and 23 h 40 min after the fetch, inside the 24-hour cap. It has crossed two midnights, so the rows `2027-03-27` and `2027-03-28` are gone and five rows are left (`2027-03-29` to `2027-04-02`). A request for 7 days gets those 5 rows with `stale: true`, a request for 6 days also gets 5, and a request for 5 days gets exactly 5, complete.
- **Single flight:** several simultaneous requests for one cell make exactly one provider call; in a failure they all get the same stale answer or the same 503 from one cycle; a waiting request that disconnects does not cancel the fetch for the others; different cells do not block or cool each other.
- **Unexpected failures:** the fake provider raises an unexpected exception whose message holds a marker secret. The request gets the failure answer (the stale list if there is one, otherwise 503), the log holds the exception class and not the marker, and the next request for the same cell works once the provider works again, because the in-flight marker was cleared. Cancelling a running cycle also clears the marker, so the cell can be fetched again and can be evicted.
- **Cool-down:** during it, no provider call and an immediate answer (stale rows, or 503 with `Retry-After` equal to the remaining time); after it, a new cycle starts; a successful fetch clears it; the 24-hour cap still applies during it.
- **Cache cap (cap 2):** the least recently used cell goes when a third arrives; an evicted cell during an outage gets the 503, not stale rows; a cell with a fetch in flight is not evicted; entries older than the stale cap are dropped.
- **Contract:** the exact set of keys in the response and in each row; `fetched_at` is UTC with `Z`; values equal the provider's; no zero or default ever appears when the provider gave none (every failure test checks the answer is a 503 or a short stale list, never a full list with made-up values).
- **Errors and health:** 404 for an unknown route and 405 for a wrong method, with their codes (`NOT_FOUND` and `VALIDATION`) and the problem+json shape (content type and the five fields). An unexpected exception inside the route returns 500 with code `UNAVAILABLE`, a fixed detail text and no `Retry-After`, and a marker secret in the exception's message is in neither the body nor the log. `GET /health` answers `{"status": "ok"}` and makes zero provider calls, also while the provider is failing and while a cell is in a cool-down.
- **Secrets:** the API key is in no `repr`, no log record (every logger at DEBUG, including httpx), no error body, no printed traceback, and no exception chain; a missing or bad variable stops startup and the message names the variable and shows no value.
- **Rules about the code:** a test that scans the service modules and fails if Open-Meteo's field names appear outside `provider.py`, and one that fails if any module refers to the registry service.
- **Optional smoke test:** exactly one test, in `tests/test_real_provider.py`, skipped unless the environment variable `RUN_REAL_PROVIDER_TEST=1` is set and never part of the default run. It fetches one cell (a neutral land point, node `48.1, 11.6`) from the real Open-Meteo through the real provider client, with the public endpoint written in the test and no key, and checks that the real answer passes every rule of 4.2. It fails if the provider changes its format, its units or its date convention. It costs one provider call.

**Settings table** (one parametrized case per row; every rejected case stops startup with an error that names the variable and the rule and shows none of the values, which a marker value in the key and URL cases checks):

| Variable | Accepted | Rejected |
|---|---|---|
| `PROVIDER_BASE_URL` (key empty) | `https://api.open-meteo.com/v1/forecast`, `http://localhost:9000/v1/forecast`, `http://example.com/x` | missing, empty, `ftp://example.com/x`, `example.com/x`, `https://` |
| `PROVIDER_API_KEY` with `PROVIDER_BASE_URL` | key set with `https://example.com/x`; key set with `http://127.0.0.1:9000/x`, `http://localhost/x`, `http://[::1]:9000/x`, `HTTP://LOCALHOST:9000/x`; key empty with `http://example.com/x`; a key of only spaces with `http://example.com/x` (counts as empty) | key set with `http://example.com/x`, `http://localhost.example.com/x`, `http://127.0.0.1.example.com/x`, `http://localhost@example.com/x`, `http://example.com/x#@localhost`, `http://192.168.1.5/x` |
| `PROVIDER_TIMEOUT_SECONDS` | `0.1`, `3`, `30` | `0`, `-1`, `30.1`, `31`, `abc`, `nan`, `inf`, empty |
| `PROVIDER_RETRIES` | `0`, `2`, `5` | `-1`, `6`, `1.5`, `abc`, empty |
| `PROVIDER_RETRY_DELAY_SECONDS` | `0`, `0.5`, `10` | `-0.1`, `10.1`, `abc`, `nan`, empty |
| `FRESH_FOR_SECONDS` | `1`, `10800` | `0`, `-5`, `abc`, empty |
| `STALE_MAX_AGE_SECONDS` | equal to `FRESH_FOR_SECONDS`, larger | smaller than `FRESH_FOR_SECONDS`, `abc`, empty |
| `COOLDOWN_SECONDS` | `0`, `30` | `-1`, `abc`, empty |
| `CACHE_MAX_CELLS` | `1`, `2000` | `0`, `-1`, `1.5`, `abc`, empty |

The defaults are checked too: with only `PROVIDER_BASE_URL` set, the settings equal the table in 4.3.

Every test that guards one of these rules must be shown to fail once, by removing the guarded behavior on purpose, and then restored (the practice used for the registry).

## 5.4 Performance (NFR-2.3)

`scripts/fake_provider.py` is a small local server (by default on `127.0.0.1:9101`) that returns valid provider-shaped data and counts its calls. `scripts/measure_p95.py` warms a few cells through the service, then sends 10 requests per second for 120 s to those cells on the service at `http://127.0.0.1:8001`, and reports p95 and the number of non-200 answers, like the registry's script. The fake provider starts its dates at the real current date in the time zone it reports, so that the first row is today at the point (4.2) and the warmed cells are fresh. It also checks that the fake provider saw **no** calls during the measurement, which proves FR-2.5 end to end. The result and its conditions go into the README, as measured.

## 5.5 README commitments

How to run, on port 8001 with **one worker** (`uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1`), because the cache and the cool-down live in one process; the settings table; what "today" means (entry 1); the stale cap and its reason, in the words of 3.3 (usually one midnight and one row, and a daylight-saving shift near midnight can cost two); that a stale answer may hold fewer rows and **a caller must check how many rows it received** (entry 2); the worst-case wait with its formula and an example (10 s with the defaults, 230 s with the largest allowed values) (3.5); why a non-empty key requires `https://` (the key is in the query string) and the local-host exception (4.3); the cool-down and its first-wait cost; the cache cap, and that per-client rate limiting is out of scope and a coordinate scan costs one provider call per new cell, so a scan over many new cells causes many parallel provider calls; that a request which joins a running cycle waits up to the worst case even when a usable stale forecast exists, because FR-2.6 asks for the retries first; what `rain_mm` includes (2.2); that only a 0.1° position is sent to the provider; Open-Meteo's limits and terms (checked 2026-11-16 on open-meteo.com/en/pricing and /en/terms): the free API allows fewer than 10,000 calls per day, 5,000 per hour and 600 per minute (300,000 per month), counted by IP address and application, with no uptime guarantee, and only for non-commercial use (the terms say what counts); Open-Meteo may block applications that misuse it; commercial use needs a paid plan, whose key goes in `PROVIDER_API_KEY` with the plan's host (`customer-api.open-meteo.com`) in `PROVIDER_BASE_URL`; that the cell cache is why the service fits inside these limits (a cell requested all day costs at most about 9 successful fetches a day: one every 3 hours plus the refresh at local midnight); that a scan over many new cells can exceed the limits, and the provider then answers with errors; that every failed attempt is retried and counts against the limit (up to 3 calls per failed cycle), and that we keep our decision of no global circuit breaker; the credit: the data comes from Open-Meteo.com and is licensed CC BY 4.0, and the README says so with the link, in the form Open-Meteo's licence page gives ("Weather data by Open-Meteo.com", linked to https://open-meteo.com/); the test and measurement commands, including the optional smoke test against the real provider (`RUN_REAL_PROVIDER_TEST=1 uv run pytest tests/test_real_provider.py -v`, one provider call, not part of the default run).

## 5.6 Requirements for later parts

- **Planner-service:** when the `days` list is shorter than the planner asked for, the planner plans only the days it has. It never fills the gap with zeros or defaults. This is also in judgment log entry 2.
- **Frontend:** wherever Open-Meteo data is shown next to a location, the frontend must show the credit "Weather data by Open-Meteo.com", with a link to https://open-meteo.com/ (the data is CC BY 4.0, and Open-Meteo's licence page asks for credit and a link to the licence next to any place the data is displayed). The response field `source: "open-meteo"` tells the frontend that the credit applies.

## 5.7 Calls made by the assistant (to check)

1. Cells are the nearest 0.1° node, not a floor; the provider is called at the node. Your example point `31.25, 34.79` falls in the cell with node `31.3, 34.8`.
2. `lat` and `lon` in the response are the caller's values, not the node.
3. `fetched_at` is UTC to the second with `Z`.
4. `PROVIDER_BASE_URL` is the full endpoint URL and the only required variable; the other names and defaults are in 4.3.
5. The strict rules of 4.2: exactly 7 rows, finite, non-negative numbers, units `mm`, consecutive dates, first row today by our clock, a known time zone. A response that breaks one is a failure.
6. A response whose first row is not today counts as a failed attempt (3.5).
7. Time zones come from the provider's IANA name (with the `tzdata` package), with the fixed offset as a fallback.
8. Every attempt has a hard total deadline, so the worst case in 3.5 is exact.
9. The cycle runs as its own shielded task, and the clock has `now`, `monotonic` and `sleep`.
10. The exact text rules of 2.1: at most 32 characters, and `.5` and `5.` rejected. (`rain_mm` as `precipitation_sum`, including showers and snow as water, was approved in the review of Part 2.)
11. Health is static; errors follow the registry's codes, including 500 as `UNAVAILABLE` without `Retry-After`.
12. `scripts/fake_provider.py` and the p95 script exist so the measurement works offline.
13. All failures are retried, including 4xx, as FR-2.6 reads.
14. The cool-down is also forgotten when its cell is evicted.
15. An empty value for a number setting is invalid (it does not fall back to the default), and the API key is stripped of surrounding spaces.
16. The check that the first row is today at the point lives in `provider.py`, which receives the clock for it (written for the builder, found in the builder read).
17. Query parameters other than `lat`, `lon` and `days` are ignored, not rejected.
18. The fake provider and the p95 script treat dates as in 5.4 (found in the builder read).

## 5.8 Left to the builder

The exact pydantic models and messages, the structure of the fake clock and fake provider, the log format, how the tests run async code, and `httpx` connection limits (left at the defaults; the per-attempt deadline covers waiting for a connection).

## 5.9 Open points

None for the user at this time. The calls above are the assistant's, for review.
