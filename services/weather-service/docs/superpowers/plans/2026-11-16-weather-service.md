# Weather service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `services/weather-service`: `GET /v1/forecast` for a point and 1 to 7 days, with a per-cell in-memory cache, single flight, a per-cell cool-down, a capped cache, and no number the provider did not give.

**Architecture:** Async FastAPI. One `ForecastService` owns freshness, single flight, the cool-down and eviction, and takes a `Provider` and a `Clock` as arguments. `provider.py` is the only code that knows Open-Meteo's names. Tests use a fake clock, a fake provider, and `httpx.MockTransport`; nothing touches the network except one optional smoke test.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, pydantic-settings, tzdata, pytest with the `anyio` plugin (already installed with FastAPI), uv.

**Spec:** `docs/superpowers/specs/2026-11-16-weather-service-design.md` (sections are cited as "spec 3.5" and so on). Decisions are in `docs/judgment-log.md`, entries 1 to 12.

All paths are relative to `services/weather-service/` unless they start with `/`.

## How every task runs

- **Stop after every task** and report: files changed, the real test output, the commit hash, and every call you made on your own. Wait for the user's OK before the next task.
- Each task ends with all tests green and one local commit. Never push. End the commit message with the attribution line given for the model that runs the task.
- **Red proofs.** A task that adds a test guarding a rule must show that test fail once: remove the guarded behavior on purpose, show the red result, restore the file, and check its checksum. The task lists the removals to try. A guard whose removal leaves the suite green is a defect in the test: report it, do not weaken it.
- If a test fails, report it with the output and stop. Do not change an assertion until the user decides.
- The model line says which model fits. If a "mechanical" task needs judgment the plan does not cover (for example a test that can never fail, or a log line that might hold a secret), stop and say which model you would use.
- Run `uv run pytest -q -p no:cacheprovider` from `services/weather-service`.

## Global Constraints

Values copied from the spec; every task includes them.

- Python `>=3.12`. Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28` (runtime), `pydantic-settings~=2.16`, `tzdata`; dev: `pytest~=9.2`. Port **8001**, one worker: `uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1`.
- No import from `services/registry-service`, and no mention of it in service code. Open-Meteo's field names (`et0_fao_evapotranspiration`, `precipitation_sum`, `daily`, `daily_units`, `utc_offset_seconds`, `forecast_days`) appear only in `provider.py` and in test or tool fakes that imitate the provider.
- Settings (`.env`, next to `config.py`; a real variable wins, even an empty one): `PROVIDER_BASE_URL` required; `PROVIDER_API_KEY` empty; `PROVIDER_TIMEOUT_SECONDS` 3 (>0, <=30); `PROVIDER_RETRIES` 2 (0 to 5); `PROVIDER_RETRY_DELAY_SECONDS` 0.5 (0 to 10); `FRESH_FOR_SECONDS` 10800; `STALE_MAX_AGE_SECONDS` 86400 (>= fresh); `COOLDOWN_SECONDS` 30 (>=0); `CACHE_MAX_CELLS` 2000 (>=1). Empty number value is invalid. A non-empty key needs `https://` unless the host is exactly `localhost`, `127.0.0.1` or `::1`.
- Request text (spec 2.1): `days` one ASCII digit 1 to 7; `lat`/`lon` match `[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?`, ASCII only, at most 32 characters, range checked on the exact decimal value; each parameter exactly once; other parameters ignored.
- Cell: `index = floor(value × 10 + 0.5)` on the decimal text with exact arithmetic (precision 2100 or fractions); key `(lat_index, lon_index)`; the provider is called at the node (one decimal) with `forecast_days=7`, `timezone=auto`, daily `et0_fao_evapotranspiration,precipitation_sum`, `apikey` only when the key is not empty.
- Fresh: age < `FRESH_FOR_SECONDS` **and** first row dated today at the point. Usable as stale: age < `STALE_MAX_AGE_SECONDS` **and** at least one row dated today or later. Never serve a row dated before today. A stale answer is never empty. A fresh answer has exactly `days` rows; a stale answer has at most `days`.
- A provider answer is accepted whole or not at all (spec 4.2): status 200, JSON object, exactly 7 consecutive valid dates with the first one today at the point (our clock, when the answer arrives), exactly 7 ET0 and 7 precipitation values that are real, finite, non-negative numbers (not `null`, string or boolean), units `mm`, a known time zone (IANA name, else fixed offset within ±18 h). Redirects are not followed.
- Fetch cycle: `1 + PROVIDER_RETRIES` attempts, each with a hard total deadline of `PROVIDER_TIMEOUT_SECONDS` around the whole call (pool wait and connect included), `PROVIDER_RETRY_DELAY_SECONDS` between attempts through the clock, all failures retried. Worst case `(retries + 1) × timeout + retries × delay`: 10 s by default, 230 s at most. A failed cycle sets `cooldown_end = monotonic + COOLDOWN_SECONDS`. `Retry-After` is the remaining cool-down in whole seconds, rounded up, at least 1.
- Errors are `application/problem+json` with `type`, `title`, `status`, `detail`, `code`: 422 `VALIDATION` (title "Unprocessable Entity"), 404 `NOT_FOUND`, 405 `VALIDATION`, 503 `UNAVAILABLE` (detail `Forecast unavailable`, with `Retry-After`), 500 `UNAVAILABLE` (no `Retry-After`, the error never sent).
- Secrets: the key is a `SecretStr`; `repr` and `str` of settings never show the key or the base URL; `httpx` and `httpcore` loggers at WARNING; only failure kinds are logged (`timeout`, `transport`, `status <code>`, `not_json`, `invalid <rule>`), never a URL, body or exception message; errors are raised after their `except` block so no `httpx` exception stays in `__context__`.
- English only. No code in this plan beyond signatures and short examples.

## Review Focus

Failure modes the spec implies that no table covers directly. Each has a named test in the task that owns the code.

1. A provider answer with `null` or a missing value in the **last** ET0 or rain entry must never become a zero (Task 6 `test_null_in_the_last_value_is_a_failure_not_a_zero`, Task 12 contract test).
2. Half-hour and extreme offsets and the date line: Asia/Kolkata (+5:30), Asia/Kathmandu (+5:45), Pacific/Kiritimati (+14), and cells at `lon` 179.99 and -179.99, which have different local dates (Task 6 time-zone tests, Task 8 midnight tests).
3. A cell that expired at local midnight while the provider is failing must answer with stale rows that start today, never a 503 that hides usable rows and never rows from yesterday (Task 8 `test_midnight_expiry_with_a_failing_provider_serves_stale_rows_from_today`).
4. Many different cells in flight at once, more than the cap: all complete, none blocks another, and the next new entry brings the cache back to the cap (Task 11 `test_cells_in_flight_beyond_the_cap_finish_and_the_cache_shrinks_back`).
5. A huge or endless provider body. The deadline stops a slow one. **A size cap is not in the spec**: this plan adds one (1 MiB, failure kind `invalid too_large`) in Task 6 and flags it for the user to confirm when reviewing the plan (Task 6 `test_a_body_over_the_size_cap_is_a_failure`).

## Shared names

These signatures are used across tasks; later tasks rely on them exactly.

- `clock.py`: `class Clock(Protocol)` with `now() -> datetime` (UTC, aware), `monotonic() -> float`, `async sleep(seconds: float) -> None`; `class SystemClock`.
- `errors.py`: `problem_response(status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> JSONResponse`; `class RequestError(Exception)` holding `problems: list[tuple[str, str]]` (field, message); `class ForecastUnavailable(Exception)` holding `retry_after: int`; `install_handlers(app: FastAPI) -> None`.
- `config.py`: `class ConfigError(Exception)`; `class Settings` with the field names above and `api_key() -> str`; `load_settings(env_file: Path | None = None) -> Settings`.
- `grid.py`: `class Cell(NamedTuple)` with `lat_index: int`, `lon_index: int`; `cell_for(lat: Decimal, lon: Decimal) -> Cell`; `node_for(cell: Cell) -> tuple[Decimal, Decimal]`.
- `schemas.py`: `class ForecastQuery(NamedTuple)` with `lat: Decimal`, `lon: Decimal`, `days: int`; `parse_forecast_query(items: Sequence[tuple[str, str]]) -> ForecastQuery`; response models `DayOut(date, et0_mm, rain_mm)` and `ForecastOut(lat, lon, source, fetched_at, stale, days)`.
- `provider.py`: frozen dataclasses `Day(date: date, et0_mm: float, rain_mm: float)`, `ProviderForecast(rows: tuple[Day, ...], tz: tzinfo)`, `Failure(kind: str)`; `class Provider(Protocol)` with `async fetch(lat: Decimal, lon: Decimal) -> ProviderForecast | Failure` (one attempt, node coordinates); `class OpenMeteoProvider(client: httpx.AsyncClient, *, base_url: str, api_key: str, timeout: float, clock: Clock)`.
- `forecast_service.py`: `class ForecastResult` with `kind: Literal["fresh", "stale", "unavailable"]`, `fetched_at: datetime | None`, `rows: tuple[Day, ...]`, `retry_after: int | None`; `class ForecastService(provider: Provider, clock: Clock, settings: Settings)` with `async get(cell: Cell, days: int) -> ForecastResult` and `async aclose() -> None`.
- `main.py`: `create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None, provider: Provider | None = None, clock: Clock | None = None) -> FastAPI`; `app = create_app()`. With no settings, the lifespan loads them and a `ConfigError` stops startup.
- `tests/fakes.py`: `FakeClock(start: datetime)` with `now()`, `monotonic()`, `async sleep()` (advances both at once), `advance(seconds)`; `provider_body(first_date: date, *, tz: str = "UTC", utc_offset_seconds: int = 0, rows: int = 7, **overrides) -> dict` (an Open-Meteo-shaped answer); `FakeProvider` (scripted outcomes, a `calls` counter, an optional gate to hold a fetch).

---

### Task 1: Skeleton, clock, errors, health

**Model:** Haiku (mechanical: files, the errors module in the registry's style).

**Files:** Create `pyproject.toml`, `clock.py`, `errors.py`, `main.py`, `tests/conftest.py`, `tests/test_errors_health.py`; generate `uv.lock`.

**Interfaces:** Produces `Clock`, `SystemClock`, `problem_response`, `RequestError`, `ForecastUnavailable`, `install_handlers`, and `create_app` with only `/health`.

- [ ] **Step 1:** Write `pyproject.toml` with the dependencies above, `package = false`, and pytest `pythonpath = ["."]`. Run `uv sync`.
- [ ] **Step 2: Write failing tests** in `tests/test_errors_health.py` (a test-only route raises the errors): `test_health_returns_ok` (`{"status": "ok"}`); `test_unknown_route_is_404_not_found` (content type `application/problem+json`, keys exactly `type,title,status,detail,code`); `test_wrong_method_is_405_with_code_validation`; `test_unexpected_error_is_500_unavailable_without_retry_after` (route raises `RuntimeError("SECRET-MARKER")`: detail `Internal server error`, no `Retry-After`, the marker in neither the body nor `caplog`); `test_forecast_unavailable_is_503_with_retry_after` (`ForecastUnavailable(7)`: header `7`, detail `Forecast unavailable`); `test_request_error_is_422` (title `Unprocessable Entity`, detail `lat: <message>`); one `@pytest.mark.anyio` test through `httpx.ASGITransport` proving async tests run (`anyio_backend` fixture returns `"asyncio"` in `conftest.py`).
- [ ] **Step 3:** Run them; expect FAIL (no modules).
- [ ] **Step 4:** Implement `clock.py`, `errors.py` (a copy of the registry's style, written here, not imported) and `create_app` with the handlers and `/health`.
- [ ] **Step 5:** Run the suite; expect all green.
- [ ] **Step 6: Red proofs:** make the 500 handler put the exception text in the detail; drop the `Retry-After` header from the 503; map 405 to `NOT_FOUND`. Each must turn its test red. Restore and check the checksum.
- [ ] **Step 7:** Commit `Add the weather-service skeleton, clock and errors`. Stop and report.

### Task 2: Settings

**Model:** Sonnet (it touches secrets and error messages). Stop and ask for a stronger model if any rejected-case test shows a value inside an error message and one fix attempt does not remove it.

**Files:** Create `config.py`, `.env.example`, `tests/test_config.py`.

**Interfaces:** Produces `ConfigError`, `Settings`, `load_settings` (shared names above). Consumes nothing.

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`: one parametrized case per row of the Settings table in spec 5.3 (accepted and rejected); `test_defaults_equal_the_table` (only `PROVIDER_BASE_URL` set); `test_dot_env_is_read_next_to_config_py_not_the_working_directory`; `test_real_variable_beats_dot_env_even_when_empty`; `test_repr_and_str_never_show_the_key_or_the_base_url`; `test_a_rejected_value_is_never_in_the_error` (marker values in the key and URL cases: the message names the variable and the rule, and neither the message nor `traceback.format_exception` holds the marker); `test_missing_base_url_error_names_the_variable`; `test_every_setting_is_in_env_example_and_the_other_way_round`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `Settings` (`SecretStr` for the key; `hide_input_in_errors`; the https-unless-local rule using the host from `urlsplit`; an error built from variable names and rules only) and `load_settings` (raises `ConfigError` after its `except` block). Write `.env.example` with every variable, placeholders, and a comment on each.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** remove the https rule; make the key a plain `str`; put the offending value into the error message; delete one variable from `.env.example`; read `.env` from the working directory. Each must turn its test red.
- [ ] **Step 6:** Commit `Read the weather-service settings with pydantic-settings`. Stop and report.

### Task 3: Cells

**Model:** Sonnet (exact arithmetic; the traps are subtle).

**Files:** Create `grid.py`, `tests/test_grid.py`.

**Interfaces:** Produces `Cell`, `cell_for`, `node_for`. Consumes `Decimal` input only.

- [ ] **Step 1: Write failing tests** for the Cells group of spec 5.3: `test_the_32_character_value_just_below_the_tie_is_index_0` (`Decimal("0.049999999999999999999999999999")` gives 0, and `0.05` gives 1); `test_tiny_exponent_is_index_0` (`1e-999`); neighbours share a cell; points across a boundary do not; negatives (`-0.05` is 0); the edges (`90` is 900, `-90`, `180` is 1800, `-180` is -1800); `0.3` is 3, `0.7` is 7, and `Decimal("0.1") + Decimal("0.2")` is 3; `31.25` is node `31.3`; `node_for` returns one-decimal values.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `cell_for` with a local decimal context of precision 2100 (or exact fractions) and `node_for`.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** use the default `Decimal` precision (the 32-character test must fail); use float arithmetic; use floor instead of nearest; round ties down. Each must turn a test red.
- [ ] **Step 6:** Commit `Map points to 0.1 degree cells with exact arithmetic`. Stop and report.

### Task 4: Request parsing and response models

**Model:** Sonnet (many traps in "valid" text).

**Files:** Create `schemas.py`, `tests/test_schemas.py`.

**Interfaces:** Produces `ForecastQuery`, `parse_forecast_query`, `DayOut`, `ForecastOut`. Consumes `RequestError` from `errors.py`.

- [ ] **Step 1: Write failing tests:** one parametrized case per row of the tables in spec 2.1 for `days`, `lat` and `lon` (accepted gives the exact `Decimal` and `int`, rejected raises `RequestError` naming the field), including the 25-digit exponents, the four-digit exponents, `1_0`, non-ASCII digits, `.5`, `5.`, a 33-character number, missing and repeated; `test_other_parameters_are_ignored`; `test_a_conversion_error_is_a_request_error_not_a_500`; response models: `test_response_has_exactly_the_agreed_keys` (`lat,lon,source,fetched_at,stale,days`; row keys `date,et0_mm,rain_mm`), `test_no_weather_field_has_a_default` (building a `DayOut` without `et0_mm` raises), `test_fetched_at_is_utc_with_z_to_the_second`, `test_source_is_open_meteo`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `parse_forecast_query` (patterns on the text first, then the value on the exact decimal, repeated parameters found in the raw items) and the response models.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** validate with `float()` (`1_0` must be accepted and its test red); remove the three-digit exponent limit (the 25-digit case must fail); allow `.5`; use `str.isdigit()` for `days`; compare the range through a float (`90.0000000000000001` accepted); give `et0_mm` a default.
- [ ] **Step 6:** Commit `Parse the forecast request text strictly and add the response models`. Stop and report.

### Task 5: Fake clock and provider body builder

**Model:** Haiku (mechanical test support).

**Files:** Create `tests/fakes.py`, `tests/test_fakes.py`.

**Interfaces:** Produces `FakeClock` and `provider_body` (shared names). Consumes `Clock`.

- [ ] **Step 1: Write failing tests** for the fakes: `test_fake_clock_moves_now_and_monotonic_together`; `test_fake_sleep_advances_time_at_once_and_yields`; `test_provider_body_has_seven_rows_starting_at_the_given_date_in_the_given_zone`; `test_provider_body_overrides_replace_a_field_or_drop_it`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run; green.
- [ ] **Step 5: Red proof:** make `FakeClock.sleep` return without advancing; `test_fake_sleep_advances_time_at_once_and_yields` must go red. Restore.
- [ ] **Step 6:** Commit `Add the fake clock and the provider body builder`. Stop and report.

### Task 6: The provider

**Model:** Sonnet (judgment: the checks that keep numbers honest, and secrets). Use the strongest model available if any secrecy test needs a second fix.

**Files:** Create `provider.py`, `tests/test_provider.py`.

**Interfaces:** Produces `Day`, `ProviderForecast`, `Failure`, `Provider`, `OpenMeteoProvider`. Consumes `Clock`, `FakeClock`, `provider_body`, `httpx.MockTransport`.

- [ ] **Step 1: Write failing tests** (MockTransport, `FakeClock`, `OpenMeteoProvider` with a small timeout like 0.05):
  - `test_a_valid_body_gives_seven_rows_and_the_zone` (values equal the body's, unrounded); `test_the_request_has_exactly_the_agreed_query` (latitude, longitude at the node, daily names, `forecast_days=7`, `timezone=auto`, no `apikey` when the key is empty, `apikey` when set).
  - One parametrized failure per kind of spec 4.2 and 5.3: status 400/500, redirect (not followed), not JSON, not an object, missing `daily`, missing array, `null`, a string, a boolean, `NaN`, negative, 6 or 8 rows, wrong units, bad date, date gap, first row not today, unknown zone without an offset, offset beyond ±18 h, a timeout, a transport error. Each returns `Failure` with the kind; none returns a forecast.
  - `test_null_in_the_last_value_is_a_failure_not_a_zero` (Review Focus 1, for ET0 and for rain).
  - Time zones: `Asia/Kolkata`, `Asia/Kathmandu`, `Pacific/Kiritimati` resolve and "today" follows them; an unknown name with `utc_offset_seconds` works as a fixed offset (Review Focus 2).
  - `test_a_client_that_blocks_before_connecting_fails_inside_the_deadline` (a client whose `send` never returns).
  - `test_a_body_over_the_size_cap_is_a_failure` (1 MiB, kind `invalid too_large`; Review Focus 5).
  - Secrets: `test_the_key_is_in_no_log_and_no_failure_kind` (a transport error whose message holds the URL with the key; `caplog` at DEBUG for every logger, and the returned `Failure.kind`, hold no key).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `OpenMeteoProvider.fetch`: build the query; one `GET` wrapped in the whole-call deadline (an `asyncio` timeout around request and body read, not httpx's per-phase timeouts); `follow_redirects=False`; read the body with the size cap; validate every rule of spec 4.2 including the first row today by `clock.now()`; return `Failure(kind)` instead of raising, with the kinds listed in Global Constraints; never format a URL, body or exception message.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** accept `null` as 0; accept 6 rows; skip the units check; skip the first-row-today check; follow redirects; use only httpx's per-phase timeout (the blocking-client test must fail); remove the size cap; log the URL. Each must turn its test red.
- [ ] **Step 6:** Commit `Add the Open-Meteo provider with strict answer checks`. Stop and report, naming the size cap as a call to confirm.

### Task 7: The fake provider

**Model:** Haiku (mechanical test support).

**Files:** Modify `tests/fakes.py`; add `tests/test_fake_provider.py`.

**Interfaces:** Produces `FakeProvider` (shared names). Consumes `Provider`, `Day`, `ProviderForecast`, `Failure`.

- [ ] **Step 1: Write failing tests:** `test_it_returns_scripted_outcomes_in_order_and_counts_calls`; `test_a_gate_holds_the_fetch_until_released`; `test_a_callable_outcome_can_raise_an_unexpected_exception`; `test_good_forecast_helper_builds_seven_rows_for_a_zone`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; green.
- [ ] **Step 5: Red proof:** make the counter not increment while gated; the first test must go red. Restore.
- [ ] **Step 6:** Commit `Add the fake provider`. Stop and report.

### Task 8: The forecast service, core rules

**Model:** Sonnet (judgment: freshness, stale rules, the fetch cycle).

**Files:** Create `forecast_service.py`, `tests/test_service_rules.py`.

**Interfaces:** Produces `ForecastResult`, `ForecastService` with `get` (single request at a time; no sharing yet) and `aclose`. Consumes `Provider`, `Clock`, `Settings`, `Cell`, `node_for`.

- [ ] **Step 1: Write failing tests** (FakeProvider, FakeClock, `Settings` built directly):
  - `test_a_fresh_forecast_makes_no_provider_call`; `test_expiry_by_age_at_the_fresh_limit`; `test_a_fresh_answer_has_exactly_days_rows` for 1 and 7.
  - Midnight expiry for a point east and west of UTC and for Kolkata and Kathmandu (fresh by age, but the first row is no longer today: refetch).
  - `test_midnight_expiry_with_a_failing_provider_serves_stale_rows_from_today` (Review Focus 3): the answer is stale, starts today, and is not a 503.
  - Cells at `lon` 179.99 and -179.99 get different local dates (Review Focus 2).
  - `test_a_stale_answer_after_the_retries_makes_three_calls_and_waits_the_delays` (the fake clock moved by 2 × delay).
  - `test_stale_rows_before_today_are_dropped_and_the_list_is_shorter`; `test_a_stale_answer_keeps_its_own_fetched_at`; `test_a_stale_answer_is_never_empty` (all rows in the past gives `unavailable`).
  - `test_the_24_hour_cap_ends_stale_service` (age at the cap gives `unavailable` with `retry_after`); `test_no_forecast_and_a_failing_provider_is_unavailable`.
  - `test_daylight_saving_two_midnights` exactly as in spec 5.3 (Europe/Berlin, fetched 2027-03-27 22:30 UTC, request at 2027-03-28 22:10 UTC): 7 days gives 5 rows, 6 days gives 5, 5 days gives 5 complete.
  - `test_a_successful_fetch_replaces_the_stored_forecast`; `test_an_unavailable_result_has_retry_after_from_the_cooldown_setting` (the cycle just failed).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the entry state (stored forecast, cool-down end), `is_fresh`, `usable_stale`, the sequential fetch cycle (attempts, delay through `clock.sleep`, all failures retried, WARNING per failed attempt and per failed cycle with the kinds), and `get` steps 1, 4 and 5 of spec 3.4. The cool-down end is set on a failed cycle; skipping during a cool-down comes in Task 10.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** drop the first-row-today part of freshness; serve rows before today; drop the stale cap; return an empty stale list; use the default delay arithmetic wrongly (no delay between attempts); compute "today" in UTC instead of the point's zone. Each must turn a test red.
- [ ] **Step 6:** Commit `Add the forecast service rules: fresh, stale and the fetch cycle`. Stop and report.

### Task 9: Single flight

**Model:** Opus (the subtle one: shared task, shield, cancellation, the `finally`, no `await` between check and start). Sonnet only if the user accepts a closer review.

**Files:** Modify `forecast_service.py`; create `tests/test_single_flight.py`.

**Interfaces:** Extends `ForecastService.get` with spec 3.4 steps 2 and 3's in-flight handling. Consumes `FakeProvider` with its gate.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.anyio`, `asyncio.gather`):
  - `test_simultaneous_requests_for_one_cell_make_one_provider_call` (for example 20 requests, gate released after all are waiting; `calls == 1`; all answers equal).
  - `test_a_failure_is_shared_by_all_waiters` (one cycle of three attempts, all get the same stale answer or the same unavailable result; `calls == 3`).
  - `test_a_waiter_that_is_cancelled_does_not_cancel_the_fetch_for_the_others`.
  - `test_different_cells_do_not_block_each_other` (one gated cell, another cell answers at once).
  - `test_an_unexpected_exception_is_a_failed_cycle_and_the_next_request_works` (the exception message holds a marker: the log has the class and not the marker; the next request, after the cool-down, succeeds and clears the marker).
  - `test_cancelling_the_cycle_clears_the_in_flight_marker` (via `aclose`, then a new service call works on the same cell).
  - `test_no_await_between_the_check_and_the_start` (many requests started in one loop turn still make one call).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement: the fetch cycle as its own task stored on the entry; waiters await it through a shield; the task never raises to waiters (success or failure value); the marker cleared in a `finally`; unexpected exceptions logged by class only and counted as a failed cycle; `aclose` cancels running tasks.
- [ ] **Step 4:** Run the suite; expect green.
- [ ] **Step 5: Red proofs:** each request fetches for itself; drop the shield (the cancelled-waiter test must fail); drop the `finally` (the marker test must fail and the cell hang, so guard the test with a timeout); put an `await asyncio.sleep(0)` between the check and the start; log the exception message. Each must turn a test red.
- [ ] **Step 6:** Commit `Share one fetch per cell between waiting requests`. Stop and report.

### Task 10: The cool-down

**Model:** Sonnet (judgment: when the provider may be called).

**Files:** Modify `forecast_service.py`; create `tests/test_cooldown.py`.

**Interfaces:** Completes spec 3.4 step 3. Consumes `FakeClock`, `FakeProvider`.

- [ ] **Step 1: Write failing tests:** `test_during_the_cooldown_there_is_no_provider_call_and_the_answer_is_immediate` (stale rows when usable); `test_during_the_cooldown_without_a_forecast_the_answer_is_unavailable_with_the_remaining_time` (`retry_after` equals the remaining cool-down rounded up, at least 1, checked at several fake times); `test_after_the_cooldown_a_new_cycle_starts`; `test_a_successful_fetch_clears_the_cooldown`; `test_the_24_hour_cap_still_applies_during_a_cooldown`; `test_a_cooldown_of_zero_turns_it_off`; `test_a_cooldown_on_one_cell_does_not_affect_another`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement the skip with `monotonic < cooldown_end` and the `retry_after` calculation. **Step 4:** Run; green.
- [ ] **Step 5: Red proofs:** ignore the cool-down (the no-call test fails); compute `retry_after` with floor instead of ceiling; never clear it on success; apply it across cells; ignore the stale cap while cooling. Each must turn a test red.
- [ ] **Step 6:** Commit `Add the per-cell cool-down after a failed refresh`. Stop and report.

### Task 11: Cache cap and eviction

**Model:** Sonnet (judgment: eviction rules and in-flight protection).

**Files:** Modify `forecast_service.py`; create `tests/test_cache_cap.py`.

**Interfaces:** Completes spec 3.6. Consumes `FakeProvider` with its gate, `FakeClock`.

- [ ] **Step 1: Write failing tests** (cap 2): `test_the_least_recently_used_cell_is_evicted_when_a_third_arrives`; `test_every_request_for_a_cell_makes_it_most_recently_used` (a fresh hit counts); `test_an_evicted_cell_during_an_outage_gets_unavailable_not_stale_rows`; `test_a_cell_with_a_fetch_in_flight_is_not_evicted`; `test_entries_older_than_the_stale_cap_are_dropped_on_insert`; `test_eviction_forgets_the_cooldown`; `test_cells_in_flight_beyond_the_cap_finish_and_the_cache_shrinks_back` (Review Focus 4: five distinct gated cells with cap 2, all complete, the next new cell brings the size back to 2).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement the ordered map, touch on every `get`, eviction that skips in-flight entries, the stale-drop on insert. **Step 4:** Run; green.
- [ ] **Step 5: Red proofs:** evict the most recently used; skip the touch on a fresh hit; evict in-flight cells; drop no old entries; keep the cool-down after eviction; evict the new entry itself. Each must turn a test red.
- [ ] **Step 6:** Commit `Cap the cache and evict the least recently used cell`. Stop and report.

### Task 12: The API and the remaining groups

**Model:** Sonnet (judgment: wiring, secrets end to end).

**Files:** Modify `main.py`; create `tests/test_api.py`, `tests/test_secrets.py`, `tests/test_code_rules.py`; extend `tests/test_errors_health.py`.

**Interfaces:** Completes `create_app` (lifespan: shared `httpx.AsyncClient` from `transport` or default, provider, service; loggers set; `aclose` and client closed at shutdown) and the route `GET /v1/forecast`. Consumes everything above.

- [ ] **Step 1: Write failing tests:**
  - Contract: `test_the_answer_has_exactly_the_agreed_keys_and_the_providers_values`; `test_stale_answers_carry_stale_true_and_their_own_fetched_at`; `test_a_failing_provider_never_gives_a_full_list_of_made_up_values` (every provider failure from Task 6 gives 503 or a short stale list; includes the null-in-the-last-value case); `test_503_has_retry_after_and_the_fixed_detail`.
  - Validation through the API: a subset of the 2.1 rows returns 422 `VALIDATION` and `FakeProvider.calls == 0`.
  - Errors and health: `GET /health` makes zero provider calls while the provider is failing and while a cell is in a cool-down.
  - Secrets: `test_the_key_is_in_no_log_error_body_or_traceback_chain` (all loggers at DEBUG including `httpx`, a provider that fails with the key in the exception text, a 500 path); `test_a_missing_base_url_stops_startup_with_a_clear_error` (the lifespan raises `ConfigError` naming the variable).
  - Code rules: `test_open_meteo_names_appear_only_in_provider_py`; `test_no_module_refers_to_the_registry_service`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement the route (raw `query_params.multi_items()` into `parse_forecast_query`, `cell_for`, `service.get`, shape `ForecastOut`, raise `ForecastUnavailable` for `unavailable`) and the lifespan. **Step 4:** Run; green.
- [ ] **Step 5: Red proofs:** let a provider failure produce zeros; query before validating; make `/health` call the provider; log the key; make the lifespan swallow `ConfigError`; add an Open-Meteo name to `main.py`; import a registry module. Each must turn a test red.
- [ ] **Step 6:** Commit `Wire the forecast route, the lifespan and the end-to-end tests`. Stop and report.

### Task 13: The optional smoke test

**Model:** Haiku (small). It makes **one** real provider call when run with the flag; run it once and report.

**Files:** Create `tests/test_real_provider.py`.

- [ ] **Step 1:** Write `test_the_real_provider_answer_passes_every_rule` (skipped unless `RUN_REAL_PROVIDER_TEST=1`): the public endpoint written in the test, no key, node `48.1, 11.6`, the real `OpenMeteoProvider` with the real clock; the result is a `ProviderForecast` with 7 rows.
- [ ] **Step 2:** Run the default suite: the test is skipped. Run `RUN_REAL_PROVIDER_TEST=1 uv run pytest tests/test_real_provider.py -v` once and report the output.
- [ ] **Step 3: Red proof:** run it once with `RUN_REAL_PROVIDER_TEST=1` and the endpoint in the test temporarily changed to `http://127.0.0.1:1/` (a closed local port, so no external call). It must fail with a transport failure, not skip and not pass. Restore the endpoint and check the file's checksum.
- [ ] **Step 4:** Commit `Add the optional smoke test against the real provider`. Stop and report.

### Task 14: The fake provider server and the p95 measurement

**Model:** Haiku (scripts). If p95 is over 100 ms, or a script errors, stop and report: do not change the script or add anything to the service.

**Files:** Create `scripts/fake_provider.py`, `scripts/measure_p95.py`.

- [ ] **Step 1:** Write `scripts/fake_provider.py`: a local server (default `127.0.0.1:9101`) that returns valid provider-shaped data whose dates start at the real current date in the zone it reports, and counts calls (readable at a path of its own).
- [ ] **Step 2:** Write `scripts/measure_p95.py`: warm a few cells through the service at `http://127.0.0.1:8001`, send 10 requests per second for 120 s to those cells, print the p95 overall and per route, the count of non-200 answers, and check that the fake provider saw no calls during the measurement.
- [ ] **Step 3:** Start the fake provider and the service (`PROVIDER_BASE_URL` pointing at the fake, one worker). Run the measurement and report the output exactly, with the conditions (machine, rate, duration). Stop both and confirm nothing listens on ports 8001 and 9101.
- [ ] **Step 4:** Commit `Add the fake provider server and the p95 measurement`. Stop and report the numbers.

### Task 15: README and the log check

**Model:** Sonnet (many factual commitments).

**Files:** Create `README.md`; modify `docs/judgment-log.md` only to correct entries that the final code makes inaccurate (in place, no "Update:" notes).

- [ ] **Step 1:** Write the README with every commitment of spec 5.5: how to run (the exact command, port 8001, one worker); the settings table with defaults; what "today" means; the stale cap and its reason in the words of spec 3.3; that a caller must check how many rows it received; the worst-case wait formula with 10 s and 230 s; the cool-down and its first-wait cost; the cache cap and what it does not limit; joiners waiting up to the worst case; what `rain_mm` includes; that only a 0.1° position goes to the provider; Open-Meteo's limits, terms and the paid-plan host; the credit line with the link; the https rule for the key; the test commands, including the smoke test; the measured p95 with its conditions from Task 14.
- [ ] **Step 2:** Check every README claim against the code and tests (timeouts, defaults, counts, names). Re-read judgment-log entries 3 to 12 against the final code and fix anything inaccurate in place.
- [ ] **Step 3:** Run `grep -n "Update:" docs/judgment-log.md` (must find nothing), confirm entries 1 to 12 have no gaps or duplicates, and check that no real key or URL appears in any file.
- [ ] **Step 4:** Run the default suite. Commit `Document the weather service`. Stop and report.

### Task 16: Final independent review

**Model:** the strongest available (Fable), as a fresh reviewer who has not seen this work. It fixes nothing.

- [ ] **Step 1:** Give the reviewer the range of this service's commits, the spec, the plan and the judgment log, and the focus points: all rules of spec 3 and 4 hold; no number the provider did not give can reach a 200; no key, URL or parameter reaches a log, error, `repr` or exception chain; every guard has a test that can fail (mutation checks on a copy); no test is vacuous; the README and the log match the code.
- [ ] **Step 2:** Run both the default suite and, if the reviewer asks, the smoke test. Report the findings ranked by severity. Fix nothing and push nothing. Stop and wait for the user's decision.

---

## Self-review

- **Spec coverage:** settings (4.3) Task 2; cells (3.1) Task 3; request text (2.1) and response (2.2) Task 4; provider and 4.2 Task 6; 3.3 to 3.5 Tasks 8 and 9; cool-down Task 10; cap (3.6) Task 11; API, errors and health (2.3, 2.4), secrets (4.4) and the code rules Tasks 1 and 12; smoke test Task 13; NFR-2.3 and 5.4 Task 14; README (5.5) Task 15.
- **Calls beyond the spec, for the user to confirm:** the 1 MiB body-size cap (Task 6); the use of the `anyio` plugin for async tests; scripts and tests living in the layout of spec 5.2.
