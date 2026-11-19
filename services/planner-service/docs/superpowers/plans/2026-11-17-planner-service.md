# Planner service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `services/planner-service`: `GET /v1/plots/{id}/plan?days=` returns a 1 to 7 day irrigation plan from a pure FAO-56 engine, the plot data of registry-service and the forecast of weather-service, and never a plan of zeros when an upstream fails.

**Architecture:** A pure `engine.py` (standard library only) holds every formula and constant. A thin async FastAPI service validates the request, calls registry and weather with a hard per-attempt deadline, checks their answers, runs the engine, and rounds only when it builds the JSON. The service keeps no state.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, pydantic-settings, pytest with the `anyio` plugin (installed with FastAPI), uv.

**Spec:** `docs/superpowers/specs/2026-11-17-planner-service-design.md` (cited as "spec 3.4" and so on). Decisions are in `docs/judgment-log.md`, entries 1 to 14.

All paths are relative to `services/planner-service/` unless they start with `/`.

## How every task runs

- **Stop after every task** and report: files changed, the real test output, the commit hash, and every call you made on your own. Wait for the user's OK before the next task.
- Each task ends with all tests green and one local commit on branch `p2`. Never push. End the commit message with the attribution line given for the model that runs the task. Code, comments, docs and commit messages are in English.
- **Red proofs.** A task that adds a test guarding a rule must show that test fail once: make the named change, show the red result, restore the file, and check the checksum. A guard whose change leaves the suite green is a defect in the test: report it, do not weaken it.
- If a test fails, report it with the output and stop. Do not change an assertion until the user decides.
- The model line is the user's choice (Sonnet for all tasks except task 3, Haiku). Never use Opus unless the user says so. If a task needs more than the plan covers, stop and say so.
- Economy: only the red proofs listed in a task. Run the full suite once at the end of the task, on its own, check it is fully green, and only then commit (never chain the commit after the test command). Keep the report short, with no long tables.
- Run `uv run pytest -q -p no:cacheprovider` from `services/planner-service`. Async tests use the `anyio` marker with an `anyio_backend` fixture that returns `"asyncio"` (copy `services/weather-service/tests/conftest.py`).
- The other two services are only references for patterns (`config.py`, `errors.py`, the retry loop). Copy the ideas, never import from them.

## Global Constraints

Values copied from the spec; every task includes them.

- Python `>=3.12`. Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28`, `pydantic-settings~=2.16`; dev: `pytest~=9.2`. `[tool.uv] package = false`, `pythonpath = ["."]`. Port **8002**: `uv run uvicorn main:app --host 127.0.0.1 --port 8002`.
- `engine.py` uses the standard library only, with no network, no clock, no environment, no settings and no rounding. It may use `datetime.date` and `timedelta`. It may not import `time`, `os`, `random`, `httpx`, `fastapi`, or call `date.today()` or `datetime.now()`.
- No import from, and no mention of, `services/registry-service` or `services/weather-service` in service code.
- Errors are `application/problem+json` with `type` (`about:blank`), `title`, `status`, `detail`, `code`: 422 `VALIDATION` (title "Unprocessable Entity"), 404 `NOT_FOUND`, 405 `VALIDATION`, 503 `UPSTREAM_UNAVAILABLE` (detail `registry-service unavailable` or `weather-service unavailable`, `Retry-After`), 500 `UNAVAILABLE` (detail `Internal server error`, no `Retry-After`).
- Crop constants (days init/dev/mid/late; Kc ini/mid/end; p; Zr): tomato 30/40/45/30, 0.6/1.15/0.80, 0.40, 0.7 m; bell-pepper 30/35/40/20, 0.6/1.05/0.90, 0.30, 0.5 m. Cumulative ends: tomato 30, 70, 115, 145; pepper 30, 65, 105, 125.
- Day count: planting date is day 0, `d = date - planting_date`. Stages: initial `d < C1`, development `C1 <= d < C2`, mid `C2 <= d < C3`, late `C3 <= d <= L`, after_cycle `d > L`.
- `TAW = soil mm/m x Zr`; `ETc = Kc x ET0`; `p = clamp(p_table + 0.04 (5 - ETc), 0.1, 0.8)`; `RAW = p x TAW`; rain counts 0 if `rain < 0.2 x ET0`; `before = min(TAW, max(0, D + ETc - rain_counted))`; `irrigation = min(max(0, before - RAW), 24 x emitter_flow / (row x spacing))`; start `D = RAW` of day 1; no Ks.
- Rounding only in the JSON: `kc` 3 decimals; every mm value and `flow_lph` 2 decimals; `litres` and `run_minutes` whole numbers from full precision; ties half up; at least 1 minute when `irrigation_mm > 0`; `et0_mm`, `rain_mm`, `fetched_at` unchanged.
- Settings (`.env` next to `config.py`; a real variable wins, even an empty one; an empty value is invalid): `REGISTRY_BASE_URL`, `WEATHER_BASE_URL` required; `REGISTRY_TIMEOUT_SECONDS` 2 (>0, <=30); `REGISTRY_RETRIES` 1 (0 to 5); `WEATHER_TIMEOUT_SECONDS` 12 (>0, <=240); `WEATHER_RETRIES` 0 (0 to 5); `RETRY_DELAY_SECONDS` 0.3 (0 to 10).
- Worst-case wait `A + max(A, B)` with `A = (RR+1) x RT + RR x delay`, `B = (WR+1) x WT + WR x delay`: 16.3 s with the defaults.
- Logs hold only the service name, the attempt number and a failure kind. Never a URL, a plot id, a body or an exception message. `httpx` and `httpcore` loggers at WARNING.

## Review Focus

Input classes the spec implies but its main tests do not exercise. Each has a test in the owning task.

- Registry numbers that are finite but huge (`area_m2 = 1e308`) make `litres` infinite. The engine raises `ValueError` (500), and `Infinity` never reaches the JSON (task 2).
- A plot id with `%2F`, spaces or non-ASCII text reaches registry percent-encoded, with no path escape (task 9).
- A plan that crosses the planting date or the cycle end inside its days: the warning looks at the first day only, every day has the right `stage` (tasks 1 and 9).
- `lat` and `lon` from registry that are integers or tiny floats (`31`, `1e-05`) are sent in a form weather accepts (task 7).
- The client disconnects while the upstream calls run (task 9): first check with one short experiment whether FastAPI cancels the handler. If it does, test that the calls are cancelled. If it does not, build no disconnect watcher: the calls end within the worst case of 16.3 s, and this is written down as a limitation in the README and as a judgment-log entry, and the test is dropped.

---

### Task 1: Engine, day count, stages and Kc (with the project scaffold)

**Model:** Sonnet. The engine decides every number: if stuck, stop and say so (the user decides on a stronger model).

**Files:**
- Create: `pyproject.toml`, `tests/conftest.py`, `engine.py`, `tests/test_engine_stages.py`

**Interfaces:**
- Produces: `CROPS: dict[str, CropParams]`; `CropParams(stage_days: tuple[int,int,int,int], kc: tuple[float,float,float], p_table: float, root_depth_m: float)` (frozen dataclass, with `cycle_length` and `cumulative_ends` properties); `day_number(planting: date, day: date) -> int`; `stage_and_kc(crop: CropParams, d: int) -> tuple[str, float]`.

- [ ] **Step 1:** scaffold `pyproject.toml` (copy the weather one; name `planner-service`, no `tzdata`), `tests/conftest.py`, and run `uv sync`.
- [ ] **Step 2: failing tests** `tests/test_engine_stages.py`: one parametrized `test_stage_and_kc_boundaries` row per row of the spec 3.2 table, both crops, comparing Kc with `pytest.approx(rel=1e-9)`: tomato `d` = -1, 0, 29 (`initial`, 0.6), 30 (`development`, 0.6), 31 (0.61375), 69 (1.13625), 70 (`mid`, 1.15), 114 (1.15), 115 (`late`, 1.15), 116 (1.138333...), 144 (0.811667...), 145 (`late`, 0.80), 146 (`after_cycle`, 0.80); pepper 29, 30, 64 (1.037143), 65 (`mid`, 1.05), 104, 105 (`late`, 1.05), 106 (1.0425), 124 (0.9075), 125 (0.90), 126 (`after_cycle`, 0.90). Plus `test_day_number_planting_day_is_zero` (`day_number(date(2026,3,1), date(2026,11,17)) == 261`) and `test_cycle_lengths` (145 and 125).
- [ ] **Step 3:** run, expect FAIL (`engine` missing).
- [ ] **Step 4:** implement the three items above. Eq. 66 interpolation as in spec 3.2.
- [ ] **Step 5:** run, expect PASS.
- [ ] **Step 6: red proofs.** In `stage_and_kc`: (a) `d <= L` to `d < L` fails the `d=145` row; (b) `d < C2` to `d <= C2` fails `d=70`; (c) interpolate with `d - 1` fails `d=31`; (d) remove the `after_cycle` branch fails `d=146`. Restore after each.
- [ ] **Step 7: commit** `Add the engine day count, stages and Kc`.

### Task 2: Engine, the daily step, litres and minutes

**Model:** Sonnet. If stuck, stop and say so.

**Files:**
- Modify: `engine.py`
- Test: `tests/test_engine_step.py`, `tests/test_engine_errors.py`, `tests/test_code_rules.py` (the purity test only, for now)

**Interfaces:**
- Consumes: task 1.
- Produces (frozen dataclasses): `PlotInput(crop_id: str, planting_date: date, area_m2: float, row_spacing_m: float, emitter_spacing_m: float, emitter_flow_lph: float, soil_mm_per_m: float)`; `WeatherRow(date: date, et0_mm: float, rain_mm: float)`; `PlanWarning(code: str, numbers: dict[str, int])`; `DayResult(date, d, stage, kc, etc_mm, p, raw_mm, rain_counted_mm, irrigation_mm, capped, litres, run_minutes, depletion_mm, bucket_mm, trigger_mm)`; `EngineResult(taw_mm, flow_lph, start_bucket_mm, days: tuple[DayResult, ...], warnings: tuple[PlanWarning, ...])`; `plan(plot: PlotInput, rows: Sequence[WeatherRow]) -> EngineResult`.

- [ ] **Step 1: failing tests** `test_engine_step.py` (spec 3.4 to 3.6): `test_p_follows_formula_and_limits` (ETc 5 gives the table p; a huge ETc clamps to 0.1; ETc 0 gives 0.6; a pepper with a very low ETc clamps at 0.8 only when the formula exceeds it); `test_rain_threshold` (rain at `0.2 x ET0 - eps` counts 0, exactly `0.2 x ET0` counts, ET0 = 0 counts any rain); `test_before_clamped_at_zero_and_taw` (rain larger than the bucket leaves `depletion_mm == 0` and nothing is carried; a tiny-flow plot keeps `depletion_mm <= taw_mm`); `test_start_at_trigger_and_overshoot_only`; `test_bucket_equals_trigger_when_irrigated_and_not_capped`; `test_cap_1440_minutes_carries_depletion` (a plot with application rate below ETc / 24 h gives `run_minutes == 1440`, `capped`, `bucket_mm < trigger_mm`, and the next day starts from the carried depletion); `test_no_ks` (after a capped day `etc_mm == kc * et0`); `test_warnings` (`planting_date_past_cycle` with `days_past_cycle = d1 - L`, `planting_date_in_future` with `days_until_planting`, none when the first day is inside the cycle even if the plan crosses `L` later, `d1 == L` gives none); `test_future_planting_is_initial_kc_ini`.
- [ ] **Step 2: failing tests** `test_engine_errors.py`: `ValueError` for each: non-positive area, row spacing, emitter spacing, flow, soil value; non-finite and negative ET0 and rain; unknown crop; empty rows; dates with a gap, a repeated date, a wrong order; and **`area_m2 = 1e308` with an irrigating day** (non-finite result, spec Review Focus).
- [ ] **Step 3: failing test** `test_code_rules.py::test_engine_is_pure`: parse `engine.py` with `ast`; allowed imports are standard library modules except `time`, `os`, `random`; forbid `httpx`, `fastapi`; forbid calls to `today` and `now`; forbid `os.environ`.
- [ ] **Step 4:** run, expect FAIL.
- [ ] **Step 5:** implement `plan` and the dataclasses exactly as in spec Part 3. Validate inputs first (`ValueError` with a short message, no values), then step the days.
- [ ] **Step 6:** run, expect PASS.
- [ ] **Step 7: red proofs.** Remove the p clamp (fails the limits test); `<` to `<=` in the rain test (threshold test); drop `max(0, ...)` in `before` (zero clamp); drop `min(TAW, ...)` (TAW clamp); drop the cap (cap test); start `D = 0` (start test); multiply `etc_mm` by a Ks (no-Ks test); remove the consecutive-date check (gap, repeat and order cases); remove the finite check on results (`1e308` case); add `import time` (purity test). Restore after each.
- [ ] **Step 8: commit** `Add the engine daily step, litres and minutes`.

### Task 3: The three hand-calculated cases

**Model:** Haiku. Tests only; the expected values are in spec 5.4. If one fails, stop and report (the engine or the spec is wrong).

**Files:**
- Test: `tests/test_engine_cases.py`

- [ ] **Step 1: tests** (`pytest.approx(abs=1e-6)`): `test_case_a_task_example` (North block, 2026-06-09, ET0 6.0: `d == 100`, `kc == 1.15`, `etc_mm == 6.9`, `p == 0.324`, `raw_mm == 39.69`, `irrigation_mm == 6.9`, `litres == 6900`, `flow_lph == 1666.666...`, `run_minutes == 248.4`, `bucket_mm == trigger_mm == 82.81`, `taw_mm == 122.5`); `test_case_b_rain_and_small_irrigation` (five days from 2026-08-10, ET0 6.25 and rain `[0, 19.7, 0.5, 0, 0]`: irrigation `[5.0, 0, 0, 0, 0.3]`, litres `[5000, 0, 0, 0, 300]`, minutes `[180, 0, 0, 0, 10.8]`, bucket `[73.5, 88.2, 83.2, 78.2, 73.5]`, trigger 73.5 each, `rain_counted_mm[2] == 0`); `test_case_c_pepper_development` (East block, 2026-06-01 and 06-02, ET0 5.6: `kc == [6/7, 0.87]`, `etc_mm == [4.8, 4.872]`, `p == [0.308, 0.30512]`, `raw_mm == [30.8, 30.512]`, `irrigation_mm == [4.8, 5.16]`, `litres == [3840, 4128]`, `flow_lph == 2133.333...`, `run_minutes == [108.0, 116.1]`, `bucket_mm == [69.2, 69.488]`).
- [ ] **Step 2:** run, expect PASS.
- [ ] **Step 3: red proofs.** Change tomato Kc end to 0.70 (case b fails); p slope 0.04 to 0.05 (cases a and c); Zr for pepper 0.5 to 0.6 (case c); the rain threshold factor 0.2 to 0.1 (case b day 3). Restore after each.
- [ ] **Step 4: commit** `Add the three hand-calculated engine cases`.

### Task 4: The request check

**Model:** Sonnet.

**Files:**
- Create: `request.py`; Test: `tests/test_request.py`

**Interfaces:**
- Produces: `class RequestError(Exception)` with `.detail: str`; `parse_days(raw_query: bytes) -> int` (absent gives 7); `plot_id_is_possible(plot_id: str) -> bool`.

- [ ] **Step 1: failing tests:** parametrized over the `days` table of spec 2.1: accepted `1`..`7` and absent (7); rejected `0`, `8`, `9`, `10`, `07`, `+3`, `-3`, ` 3`, `3 `, `3.0`, `3.5`, `3e0`, `٣`, `３`, empty, repeated. Every rejected case raises `RequestError("days: must be one digit from 1 to 7")`. Other parameters are ignored. `plot_id_is_possible` is false for 65 characters and for a NUL, true for 64 characters.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement on the raw query string (`parse_qsl` with `keep_blank_values=True`), checking text with a regex `[1-7]` (ASCII only), never `int()`.
- [ ] **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Replace the check with `int()` (fails `٣`, `３`, ` 3`, `07`); count only the first `days` (fails repeated); treat empty as absent (fails empty). Restore after each.
- [ ] **Step 6: commit** `Add the request check for days and the plot id`.

### Task 5: Settings

**Model:** Sonnet. Copy the approach of `services/weather-service/config.py`.

**Files:**
- Create: `config.py`, `.env.example`; Test: `tests/test_config.py`

**Interfaces:**
- Produces: `class ConfigError(Exception)`; `Settings` (fields `registry_base_url`, `weather_base_url`, `registry_timeout_seconds`, `registry_retries`, `weather_timeout_seconds`, `weather_retries`, `retry_delay_seconds`; the two URLs hidden from `repr`); `load_settings(env_file: str | None = None) -> Settings`.

- [ ] **Step 1: failing tests:** one parametrized case per row of the spec 5.3 settings table (accepted and rejected); the defaults; a real empty variable beats `.env`; `.env` is read next to `config.py`; every rejected case raises `ConfigError` naming the variable and the rule, with a marker value absent from the message; `repr(Settings)` shows no URL; `test_env_example_matches_settings` (every setting appears in `.env.example` and the other way round).
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement; strip one trailing `/` from the URLs; reject user info, query, fragment. **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Remove the user-info check; allow an empty number; remove `repr=False` on a URL; remove one variable from `.env.example`. Restore after each.
- [ ] **Step 6: commit** `Add the planner settings`.

### Task 6: The checks of the upstream answers

**Model:** Sonnet. Rules are in spec 4.4.

**Files:**
- Create: `upstream.py` (checks only); Test: `tests/test_upstream_checks.py`

**Interfaces:**
- Produces: `class InvalidAnswer(Exception)` with `.rule: str`; `PlotData(crop_id, soil_id, emitter_id, planting_date: date, area_m2, row_spacing_m, emitter_spacing_m, lat, lon)`; `Forecast(stale: bool, fetched_at: str, rows: tuple[WeatherRow, ...])`; `parse_plot(body: object) -> PlotData`; `parse_soil(body: object) -> float`; `parse_emitter(body: object) -> float`; `parse_forecast(body: object, days_requested: int) -> Forecast`.

- [ ] **Step 1: failing tests:** a valid body for each; every failure of spec 4.4 one by one (not an object, a missing field, `null`, string, boolean, `NaN`, zero or negative where it must be positive, bad date, `lat` 91, `lon` -181, empty ids; forecast: 0 rows, more than asked, a gap, a repeated date, negative or non-finite `et0_mm`/`rain_mm`, `source` not `open-meteo`, `stale` not a boolean, a bad `fetched_at`); fewer rows than asked is valid; each raises `InvalidAnswer` with a rule name.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement; a boolean is not a number; accept ints and floats. **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Accept booleans as numbers (boolean cases); drop the consecutive check (gap and repeat); allow 0 rows; drop the `source` check. Restore after each.
- [ ] **Step 6: commit** `Add the checks of the upstream answers`.

### Task 7: The upstream client: retries, hard deadline, failure kinds

**Model:** Sonnet. The worst-case wait lives here: if stuck, stop and say so.

**Files:**
- Modify: `upstream.py`; Create: `clock.py`; Test: `tests/test_upstream_client.py`, `tests/fakes.py`

**Interfaces:**
- Consumes: `load_settings` fields; task 6.
- Produces: `real_sleep(seconds: float) -> Awaitable[None]` in `clock.py`; `class UpstreamFailure(Exception)` with `.service: str`, `.kind: str`, `.retry_after: int`; `class NotFound(Exception)`; `class Upstream` with `__init__(self, service: str, base_url: str, http: httpx.AsyncClient, timeout: float, retries: int, delay: float, sleep, retry_4xx: bool)` and `async get_json(self, path: str, params: dict[str, str] | None = None, *, not_found_ok: bool = False) -> object`; `forecast_query(lat: float, lon: float, days: int) -> dict[str, str]` (shortest decimal text via `repr`).
- Failure kinds: `timeout`, `transport`, `status <code>`, `not_json`. `retry_after` is the upstream's `Retry-After` if a whole number 1 to 60, else 5.

- [ ] **Step 1: failing tests** with `httpx.MockTransport` and a fake `sleep` that records delays: registry-style (`retry_4xx=False`): 5xx, timeout and transport error are retried and a later success returns the body; a 404 raises `NotFound` when `not_found_ok` (otherwise a failure) and is not retried; another 4xx is not retried; weather-style (`retries=0`): any failure fails at once; with `retries=2`, all failures are retried; the delay is slept between attempts and never after the last; redirects fail; `Retry-After` handling (`7` kept, `0`, `61`, `abc` and absent give 5); a client that blocks before connecting and never returns still fails each attempt inside the deadline, and a whole cycle ends within `(retries + 1) x timeout + retries x delay` plus a small margin (timeout about 0.05 s); `forecast_query(31, 1e-05, 3)` gives `{"lat": "31", "lon": "1e-05", "days": "3"}` text that matches weather's `lat`/`lon` pattern (spec Review Focus); an exception whose message holds a marker is logged by class only and counts as a failed attempt; the log has the service name, attempt number and kind and nothing else.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement; wrap each attempt in `asyncio.timeout(timeout)`; translate httpx errors after the `except` block ends (no httpx exception in `__context__`); set `httpx` and `httpcore` loggers to WARNING in `main.py` later (task 9). **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Remove the `asyncio.timeout` (the blocking-client test hangs, use a pytest timeout); retry on 404 (not-retried test); retry 4xx for registry style; sleep after the last attempt; keep the exception in `__context__`; log the exception message. Restore after each.
- [ ] **Step 6: commit** `Add the upstream client with retries and a hard deadline`.

### Task 8: Output: rounding and the plan JSON

**Model:** Sonnet.

**Files:**
- Create: `output.py`; Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `EngineResult`, `PlotData`, `Forecast`.
- Produces: `round_half_up(value: float, digits: int) -> float`; `to_plan_json(plot_id: str, plot: PlotData, forecast: Forecast, result: EngineResult, days_requested: int) -> dict`.

- [ ] **Step 1: failing tests:** the exact key sets at the top level, in a day and in a warning (spec 2.2); `round_half_up(0.125, 2) == 0.13` and `round_half_up(2.675, 2) == 2.68` (decimal text, not binary float); `kc` has 3 decimals; litres and minutes are ints computed from full precision (not from the rounded mm); a day with `irrigation_mm` 0.001 gives `run_minutes >= 1`, and `run_minutes == 0` only when irrigation is 0; `stale` on every day equals the forecast's; `forecast_short` appears only when fewer rows than asked, with `days_requested` and `days_received`; warning order (planting first); `assumed_start == {"rule": "at_trigger", "bucket_mm": <rounded>}`; `forecast == {"source": "open-meteo", "fetched_at": <unchanged>}`; `et0_mm` and `rain_mm` unchanged; no `Infinity` or `NaN` can be serialised (`json.dumps(..., allow_nan=False)`).
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement with `Decimal`. **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Use `round()` (tie cases); compute litres from the rounded mm; remove the 1-minute minimum; hand out `stale` from the day instead of the forecast. Restore after each.
- [ ] **Step 6: commit** `Add the plan JSON and the rounding`.

### Task 9: The service and the API

**Model:** Sonnet. Parallel calls, first failure wins, cancellation: if stuck, stop and say so.

**Files:**
- Create: `planner.py`, `errors.py`, `main.py`; Test: `tests/test_api.py`, `tests/test_errors_health.py`

**Interfaces:**
- Consumes: tasks 2, 4, 5, 6, 7, 8.
- Produces: `async build_plan(plot_id: str, days: int, registry: Upstream, weather: Upstream) -> dict` (raises `NotFound`, `UpstreamFailure`); `problem_response(status: int, code: str, detail: str, headers: dict[str, str] | None = None)` (registry's style); `create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None, sleep=None) -> FastAPI`; `app`; routes `GET /v1/plots/{plot_id}/plan` and `GET /health`. The plot id is percent-encoded with `quote(plot_id, safe="")`.

- [ ] **Step 1: failing tests** (fake upstreams through `MockTransport`): a fresh plan; a stale plan (every day `stale: true`); a short plan with `forecast_short` and no padding; 404 for an unknown plot with no weather call, and for a 65-character id with no registry call; `422` for each bad `days`, with no upstream call; 503 naming registry for each registry failure and 503 naming weather for each weather failure, with `Retry-After`; a soil 404 gives 503 naming registry; the first failure wins and the sibling calls are cancelled (a never-answering fake is cancelled); (only if the experiment in the Review Focus shows FastAPI cancels the handler on disconnect) a client disconnect cancels the upstream calls; a plot id `a%2Fb c é` reaches registry percent-encoded; a plan whose first day is before the planting date and crosses it has `planting_date_in_future` and right `stage` per day; one whose first day is the last cycle day has no warning and its next day is `after_cycle`; an unknown `crop_id` gives 500 `UNAVAILABLE` with the fixed detail and no `Retry-After`; an unexpected exception gives the same 500 and a marker in its message is in neither body nor log; 404 route and 405 method with their codes; problem+json shape; `GET /health` returns `{"status": "ok"}` and makes zero upstream calls while both fail; every failure test asserts the answer is not a 200.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement; `asyncio.TaskGroup` for the parallel step (cancels siblings on failure; unwrap the `ExceptionGroup`); set the `httpx` and `httpcore` loggers to WARNING at startup. **Step 4:** run, expect PASS.
- [ ] **Step 5: red proofs.** Run the calls in sequence with `gather(return_exceptions=True)` (first-failure test); swallow a failed call and plan with zeros (no-200 tests); drop the plot-id guard; drop `quote` (percent-encoding test); let `stale` default to false; remove the 500 handler. Restore after each.
- [ ] **Step 6: commit** `Add the plan service and the API`.

### Task 10: Secrets, logging and code rules

**Model:** Sonnet.

**Files:**
- Test: `tests/test_secrets.py`, `tests/test_code_rules.py` (extend)

- [ ] **Step 1: tests:** with every logger at DEBUG, no record holds a URL, a plot id, a body or an exception message (markers in each) across a failing registry, a failing weather and an invalid answer; a failed attempt logs `service`, attempt number and kind; `httpx` and `httpcore` are at WARNING after startup; no exception that escapes holds an httpx exception in `__cause__` or `__context__`; `repr(settings)` shows no URL; `test_no_imports_from_other_services` scans every service module for `registry-service`, `registry_service`, `weather-service` and `weather_service`.
- [ ] **Step 2:** run. Expect PASS (the code exists); any red result is a bug to report and fix in the owning task's file.
- [ ] **Step 3: red proofs.** Log the failing URL; log `str(exc)`; leave the httpx loggers at INFO; add a comment-free import of a path under `services/registry-service`. Restore after each.
- [ ] **Step 4: commit** `Add the tests of secrets, logging and code rules`.

### Task 11: README

**Model:** Sonnet.

**Files:**
- Create: `README.md`; Test: `tests/test_readme_example.py`

- [ ] **Step 1: failing test** `test_readme_plan_example_matches_output`: build the spec's North block example (2026-11-17, three days, fake upstreams), parse the first ```json block under "Plan example" in the README, and compare parsed values (not text) with the service output.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** write the README as listed in spec 5.6 (run, settings table, worst case 16.3 s and 1720 s, the plan JSON and field table, rounding, failure table, limitations of 3.9, the 4-calls-per-plan note, `PATCH /v1/plots/{id}`, the Open-Meteo credit, test commands, and an optional Mermaid sequence diagram). **Step 4:** run, expect PASS.
- [ ] **Step 5: red proof.** Change one number in the README example; the test fails. Restore.
- [ ] **Step 6: commit** `Document the planner service`.

### Task 12: The knowledge skill `irrigation-calc-reference`

**Model:** Sonnet, reviewed by the user.

**Files:**
- Create: `.claude/skills/irrigation-calc-reference/SKILL.md`

- [ ] **Step 1:** write the skill from `engine.py` as built and spec Part 3: when to use it (any question about how a number of the plan is calculated), the formulas with units, the constants with their FAO-56 source tables, the day-count convention, the limitations of 3.9, and the three cases of spec 5.4 as worked examples with every intermediate value. Frontmatter `name` and `description` as in `services/registry-service/.claude/skills/registry-api/SKILL.md`.
- [ ] **Step 2:** check that each case value in the skill appears in `tests/test_engine_cases.py` (a grep, reported in the output).
- [ ] **Step 3: commit** `Add the irrigation-calc-reference skill`.

---

## Self-review

- **Spec coverage:** 2.1 task 4; 2.2 task 8; 2.3 and 2.4 task 9; Part 3 tasks 1 to 3; 4.1 task 9; 4.2 task 5; 4.3 task 7; 4.4 task 6; 4.5 tasks 7, 9, 10; 5.3 code rules tasks 2 and 10; 5.4 task 3; 5.6 task 11; skill task 12. No gap found.
- **Types:** `PlotData`, `Forecast` (task 6) feed `plan` through `PlotInput` and `WeatherRow` (task 2) in `planner.py` (task 9); `Upstream.get_json` and `UpstreamFailure.retry_after` (task 7) are what task 9 maps to `Retry-After`.
- **Proportion:** the plan holds signatures, test names, values and red proofs, and no code bodies.
