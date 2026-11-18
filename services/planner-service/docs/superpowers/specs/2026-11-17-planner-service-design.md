# Planner service: design

Status: approved by the user on 2026-11-17 (after review in five parts and a builder read). Branch: `p2`. Date: 2026-11-17.
Part of task P2. The registry-service and weather-service parts are finished. This service shares no code with them.
Decisions already in `docs/judgment-log.md`: entry 1 (depletion fraction p), 2 (start level, irrigation depth, 1440-minute cap), 3 (rain), 4 (stage lengths and Kc values), 5 (after the cycle), 6 (root depth), 7 (the bucket level in the plan), 8 (the plan JSON), 9 (calls to registry and weather), 10 (very small irrigations are kept), 11 (day count and no Ks), 12 (the weather rows are checked twice). Research: `docs/research/fao56.md`.

---

# Part 1. Intent and scope

## 1.1 What this is and why

`planner-service` answers the grower's question: "Should I water this plot today, and for how many minutes?" For one plot it returns a plan for the next 1 to 7 days, starting today. For each day it says how much water to apply (mm, litres, minutes of drip running), why (the crop factor and its stage, the rain counted, the level of the soil-water bucket), and whether the weather behind it is stale.

It combines three things. The plot, its soil and its emitter come from `registry-service`. The daily ET0 and rain at the plot's coordinates come from `weather-service`. The rules come from our own engine: a daily soil-water bucket after FAO-56 (single crop coefficient, Kc from the growth stage, depletion fraction p, readily available water RAW, depth in mm turned into litres and then into minutes of running).

The reason the design is strict is the same as in weather-service. A plan of zeros reads as "no water needed", and a number nobody can trace reads as advice. So every number comes from the engine, every day of the plan comes from a real weather row, and a failure upstream is an honest 503, never a plan of zeros.

## 1.2 Requirements and where they are handled

| Requirement | Where |
|---|---|
| FR-2.9 `GET /v1/plots/{id}/plan?days=` for the next `days` days (1 to 7, default 7), starting today | 2.1, 2.2, 4.1 |
| FR-2.10 per day `date`, `et0_mm`, `kc`, `litres`, `run_minutes`, `stale`, and the bucket level at the end of the day; no irrigation means `run_minutes: 0` | 2.2, 3.6, 3.7 |
| FR-2.11 every number calculated as written in our skill, from the plot, its soil, its emitter and the forecast | Part 3 |
| FR-2.12 bad `days`: 422 `VALIDATION`; unknown plot: 404 `NOT_FOUND` | 2.1, 2.3, 4.3 |
| FR-2.13 a stale forecast still gives a plan, every affected day `stale: true` | 2.2, 4.3 |
| FR-2.14 registry or weather down or too slow: 503 `UPSTREAM_UNAVAILABLE`, detail names the service, never a plan of zeros | 2.3, 4.2, 4.3 |

The task lists no non-functional requirement for the planner. The service listens on port 8002.

## 1.3 Goals, non-goals, anti-goals

Goals
- Every number in a 200 answer was computed by the engine from the plot, the soil, the emitter and the provider's rows. No AI model computes or adjusts any irrigation number.
- The engine is a pure module: numbers in, numbers out, no network, no clock, no files. It can be turned into the knowledge skill `irrigation-calc-reference` later (formulas, units, three hand-calculated cases) without changing its behaviour.
- Every day of the plan is a day weather gave. A shorter forecast gives a shorter plan with a warning, and nothing is padded (weather-service judgment log, entry 2).
- A plan can be checked by hand: each day carries the intermediate values (`etc_mm`, `rain_counted_mm`, `irrigation_mm`) and the engine's choices are visible (`stage`, `capped`, `assumed_start`, `warnings`).
- The limits of the method are written down, in the README and in the judgment log, as limitations and not as hidden behaviour.
- Settings come from `.env` through pydantic-settings in one `config.py`. A missing required variable stops startup with a clear error.

Non-goals
- No database, no files, no cache: the planner is stateless and asks registry and weather on every request (weather has its own cache).
- No irrigation history and no soil-moisture sensor input: the starting level of the bucket is an assumption (judgment log, entry 2).
- No dual crop coefficient, no adjustment of Kc for wind or humidity (weather-service gives only ET0 and rain), no salinity, no frost, no fertigation.
- No write endpoints, no authentication, no metrics endpoint, no per-client rate limiting: each plan request makes 4 upstream calls (the plot, the soil, the emitter and the forecast), and a caller that asks for many plots causes that many calls. The README says so.
- No safety margin, and no memory of missed irrigations (judgment log, entry 2): the crop is kept on the edge of the no-stress limit, and a skipped irrigation is not remembered or recovered between requests. Only inside one plan does the 1440-minute cap carry depletion from one day to the next.
- The plan gives minutes of running per day, not the time of day and not a split into sessions.
- No planting-season logic: one row of Table 11 per crop (judgment log, entry 4).
- No registry changes: the stage lengths and Kc values live in the engine.

Anti-goals (a failure even if the tests pass)
- A 200 answer built from anything the weather service did not give: a zero, a default, an interpolated or invented value, or a date from our own clock.
- A plan of zeros when an upstream service is down, invalid or empty (FR-2.14).
- A number in the plan that cannot be reproduced by hand from the row and the documented formulas.
- A plan that hides what it assumed: the start level, the kind of stage (`after_cycle`), a short forecast and a planting date outside the crop cycle must each be visible in the answer.
- A URL, a response body, an exception message or a setting value in any log line, error message or `repr` (logs hold the service name and the failure kind only).
- Code that imports from `services/registry-service` or `services/weather-service`.
- The engine reading the clock, the network, the settings or the environment.

## 1.4 Constraints from the task and from earlier parts

- Python 3.12, FastAPI, uvicorn, uv, pydantic-settings, `httpx`, like the other two services. Own `.venv`, `.env`, `.env.example`, `README.md`, `config.py`, `tests/`.
- Errors are `application/problem+json` with the codes `VALIDATION` (422), `NOT_FOUND` (404) and `UPSTREAM_UNAVAILABLE` (503), in the registry's style (`type`, `title`, `status`, `detail`, `code`).
- `.env.example` is committed with placeholders only. `.env` is never committed.
- The README holds the plan JSON example (the task asks for it), the settings table, the worst-case wait, the limitations, and the Open-Meteo credit note for the frontend (the plan's `forecast.source` is `"open-meteo"`).
- The engine's numbers must match the task's worked example: 1000 m², tomato at mid-season, ET0 6.0 mm, no rain, rows 1.5 m apart, emitters every 0.4 m at 1.0 L/h gives `kc` 1.15, `litres` 6900 and `run_minutes` 248 (judgment log, entry 2, hand-checked).
- Soils in the registry carry `available_water_mm_per_m`, which is (thetaFC - thetaWP) x 1000, so TAW = that value x root depth (judgment log, entry 6).

---

# Part 2. The API

## 2.1 Request

`GET /v1/plots/{plot_id}/plan?days={days}`

- `plot_id` is passed to the registry percent-encoded, unchanged. An id longer than 64 characters or holding a NUL character cannot exist in the registry, so it answers 404 `NOT_FOUND` at once, without a registry call (my call, a guard against needless upstream traffic). Registry ids are UUIDs, and any unknown id is a 404 there too.
- `days` is optional. Absent means 7. When present it must appear exactly once (a repeated parameter is found from the raw query string) and be exactly one ASCII digit, `1` to `7`. No sign, no spaces, no leading zero, no non-ASCII digit, not empty. The text is checked against this pattern, never with `int()` (Python accepts `1_0`, spaces and non-ASCII digits there). Other query parameters are ignored.
- The check happens before any upstream call, so a bad request never reaches registry or weather.

One parametrized test case per row:

| Parameter | Accepted | Rejected (422 `VALIDATION`) |
|---|---|---|
| `days` | absent (means 7), `1` to `7` | `0`, `8`, `9`, `10`, `07`, `+3`, `-3`, ` 3`, `3 `, `3.0`, `3.5`, `3e0`, `٣` (Arabic-Indic digit), `３` (full-width digit), empty, repeated (`days=1&days=2`) |

## 2.2 Response (200)

The example is the North block of the seed data on 2026-11-17: 261 days after planting, so every day is `after_cycle`. Every value was computed by hand from the decisions in the judgment log.

```json
{
  "plot_id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
  "crop_id": "tomato",
  "area_m2": 1000,
  "flow_lph": 1666.67,
  "taw_mm": 122.5,
  "assumed_start": {"rule": "at_trigger", "bucket_mm": 60.76},
  "forecast": {"source": "open-meteo", "fetched_at": "2026-11-17T06:12:40Z"},
  "warnings": [
    {"code": "planting_date_past_cycle", "days_past_cycle": 116}
  ],
  "days": [
    {"date": "2026-11-17", "stage": "after_cycle", "stale": false,
     "et0_mm": 3.0, "kc": 0.8, "etc_mm": 2.4,
     "rain_mm": 0.0, "rain_counted_mm": 0.0,
     "irrigation_mm": 2.4, "litres": 2400, "run_minutes": 86, "capped": false,
     "bucket_mm": 60.76, "trigger_mm": 60.76},
    {"date": "2026-11-18", "stage": "after_cycle", "stale": false,
     "et0_mm": 2.8, "kc": 0.8, "etc_mm": 2.24,
     "rain_mm": 12.0, "rain_counted_mm": 12.0,
     "irrigation_mm": 0.0, "litres": 0, "run_minutes": 0, "capped": false,
     "bucket_mm": 70.52, "trigger_mm": 59.98},
    {"date": "2026-11-19", "stage": "after_cycle", "stale": false,
     "et0_mm": 3.4, "kc": 0.8, "etc_mm": 2.72,
     "rain_mm": 0.3, "rain_counted_mm": 0.0,
     "irrigation_mm": 0.0, "litres": 0, "run_minutes": 0, "capped": false,
     "bucket_mm": 67.8, "trigger_mm": 62.33}
  ]
}
```

Top level:

| Field | Type, unit | Meaning |
|---|---|---|
| `plot_id` | text | the plot asked for, as the registry has it |
| `crop_id` | text | the plot's crop (`tomato` or `bell-pepper`) |
| `area_m2` | number, m² | the plot's area |
| `flow_lph` | number, L/h | total flow of the plot's emitters: `area_m2 / (row_spacing_m x emitter_spacing_m) x emitter flow_lph` (3.6) |
| `taw_mm` | number, mm | total available water of the root zone: soil `available_water_mm_per_m` x root depth (3.3) |
| `assumed_start` | object | the assumption the plan starts from. `rule` is always `"at_trigger"` (judgment log, entry 2): the bucket starts at the trigger level of day 1. `bucket_mm` is that level (`taw_mm` minus RAW of day 1) |
| `forecast` | object | `source` is always `"open-meteo"` (the frontend must show the Open-Meteo credit next to it). `fetched_at` is weather's `fetched_at` unchanged, UTC with `Z`, so the age of the forecast is visible |
| `warnings` | list | zero or more objects, each with a stable `code` and its numbers, never free text. Empty when there is nothing to warn about. Order: the planting warning first, then `forecast_short` |
| `days` | list | one object per day, in date order |

Warning codes (the list is closed; the numbers are whole numbers):

| `code` | Numbers | When |
|---|---|---|
| `planting_date_past_cycle` | `days_past_cycle` | the first plan day is after the last day of the crop cycle (3.2). `days_past_cycle` is how many days after (at least 1) |
| `planting_date_in_future` | `days_until_planting` | the plot's planting date is after the first plan day. `days_until_planting` is how many days (at least 1) |
| `forecast_short` | `days_requested`, `days_received` | weather returned fewer rows than asked (judgment log, entry 2 of weather-service) |

Each day:

| Field | Type, unit | Meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | the local date at the plot, exactly as weather gave it. The first day is today (weather's entry 1) |
| `stage` | text | `initial`, `development`, `mid`, `late` or `after_cycle` (3.2). Before the planting date (`planting_date_in_future`) it is `initial` |
| `stale` | bool | `true` when weather's answer was stale. The same for all days of one plan, because one forecast answers one plan |
| `et0_mm` | number, mm | weather's ET0, unchanged |
| `kc` | number | the crop coefficient of the day (3.2) |
| `etc_mm` | number, mm | `kc x et0_mm` (3.3) |
| `rain_mm` | number, mm | weather's rain, unchanged |
| `rain_counted_mm` | number, mm | the rain that enters the bucket: 0 if `rain_mm` is below `0.2 x et0_mm`, otherwise `rain_mm` (judgment log, entry 3) |
| `irrigation_mm` | number, mm | the net depth to apply (3.5) |
| `litres` | whole number, L | `irrigation_mm x area_m2` (3.6) |
| `run_minutes` | whole number, min | minutes of drip running for `litres` at `flow_lph` (3.6). 0 means no irrigation that day. Never above 1440 |
| `capped` | bool | `true` when the 1440-minute cap cut the day (3.5) |
| `bucket_mm` | number, mm | the water in the bucket at the end of the day: `taw_mm` minus depletion (judgment log, entry 7) |
| `trigger_mm` | number, mm | the level at which irrigation starts that day: `taw_mm` minus that day's RAW. It can change from day to day, because RAW follows ETc through p (judgment log, entry 1) |

Rules:
- **Rounding only here.** The engine keeps full precision. `kc` is rounded to 3 decimals, every mm value and `flow_lph` to 2 decimals, `litres` and `run_minutes` to whole numbers, each from the full-precision value, never from another rounded field. A day with irrigation never shows fewer than 1 minute, so `run_minutes: 0` always means no irrigation. A rounded number is a plain JSON number without padding zeros (`0.8`, not `0.800`). `3.0` and `3` are the same JSON number, so tests and the README check compare parsed values, not text; `litres` and `run_minutes` are written as integers. `et0_mm`, `rain_mm` and `fetched_at` are weather's values unchanged.
- **On a day with irrigation, `bucket_mm` equals `trigger_mm`.** The overshoot rule ends the bucket exactly on the trigger (judgment log, entry 2). A chart shows the level sitting on the line. This is the intended behaviour. The exception is a capped day, where the bucket ends below the trigger.
- **The number of days.** The list has one row per row weather gave, between 1 and the `days` asked. A fresh answer from weather has exactly `days` rows, a stale one may have fewer. The planner plans only those days and never pads (anti-goal in 1.3).
- **`stale`.** One weather answer is fresh or stale as a whole, so every day carries the same value (FR-2.13).
- No other fields. The names of weather's fields and the registry's field names never appear, except `plot_id` and `crop_id`, which are the registry's ids.

## 2.3 Errors

All errors are `application/problem+json` with `type`, `title`, `status`, `detail` and `code`, built the way `services/registry-service/errors.py` builds them (this service has its own copy and imports nothing from the other services).

| Case | Status | `code` | `detail` and notes |
|---|---|---|---|
| Bad `days` | 422 | `VALIDATION` | title "Unprocessable Entity", detail `days: must be one digit from 1 to 7` |
| Unknown plot (registry 404, or an id that cannot exist, 2.1) | 404 | `NOT_FOUND` | detail `Plot not found`. No weather call |
| Unknown route | 404 | `NOT_FOUND` | |
| Method not allowed | 405 | `VALIDATION` | same choice as the other services |
| Registry or weather down, too slow, answering with an error or an invalid body (4.3) | 503 | `UPSTREAM_UNAVAILABLE` | detail `registry-service unavailable` or `weather-service unavailable`. Header `Retry-After`: the upstream's value if it is a whole number from 1 to 60, otherwise 5 (judgment log, entry 9) |
| Unexpected error, including a `crop_id` the engine does not know | 500 | `UNAVAILABLE` | fixed detail `Internal server error`, no `Retry-After`, the real error is never sent (registry's choice) |

```json
{"type":"about:blank","title":"Unprocessable Entity","status":422,"detail":"days: must be one digit from 1 to 7","code":"VALIDATION"}
{"type":"about:blank","title":"Not Found","status":404,"detail":"Plot not found","code":"NOT_FOUND"}
{"type":"about:blank","title":"Service Unavailable","status":503,"detail":"weather-service unavailable","code":"UPSTREAM_UNAVAILABLE"}
```

The detail of a 503 is a fixed text. It names the service and carries nothing from the upstream's answer. A 200 answer, stale or not, never has `Retry-After`.

## 2.4 Health

`GET /health` returns `{"status": "ok"}`. It never calls registry or weather, so a status line in the frontend cannot use up an upstream's capacity or be slowed by it, and it says only that the planner process is up.

---

# Part 3. The engine rules

The engine is a pure module (5.2): plain numbers and dates in, plain numbers out. It does no network, reads no clock, no settings and no environment, and it does not round. Everything here is the rule it implements. All the numbers come from the judgment log and `docs/research/fao56.md`.

## 3.1 Inputs and constants

Inputs: the plot (`crop_id`, `planting_date`, `area_m2`, `row_spacing_m`, `emitter_spacing_m`), the soil's `available_water_mm_per_m`, the emitter's `flow_lph`, and the weather rows (`date`, `et0_mm`, `rain_mm`), in date order.

Constants per crop (judgment log, entries 1, 4 and 6; FAO-56 Tables 11, 12 and 22):

| | tomato | bell-pepper |
|---|---|---|
| Stage lengths, days: initial, development, mid, late | 30, 40, 45, 30 | 30, 35, 40, 20 |
| Cumulative ends C1, C2, C3 and cycle length L | 30, 70, 115, 145 | 30, 65, 105, 125 |
| Kc initial, mid, end | 0.6, 1.15, 0.80 | 0.6, 1.05, 0.90 |
| p (Table 22, at ETc about 5 mm/day) | 0.40 | 0.30 |
| Root depth Zr, m | 0.7 | 0.5 |

Global constants: the rain threshold factor 0.2, the p slope 0.04 per mm/day, the p limits 0.1 and 0.8, and the daily cap of 1440 minutes.

## 3.2 Day count, stages and Kc

**Convention: the planting date is day 0.** `d = (date - planting_date)` in whole days, which is also FAO's day number `i` in Eq. 66. This is the convention behind `days_past_cycle = d - L` (261 - 145 = 116 for the North block). The cycle covers `d = 0` to `d = L`: Kc reaches Kc end on day `L`, as the interpolation of Eq. 66 gives, so the cycle spans `L + 1` calendar days, one more than the length FAO prints. That one-day difference is far inside the accuracy of Table 11.

Stages and Kc, with `C1`, `C2`, `C3`, `L` from the table (a boundary day belongs to the later stage, except `L`):

| `d` | `stage` | `kc` |
|---|---|---|
| `d < C1` (this includes `d < 0`, a planting date in the future) | `initial` | Kc initial |
| `C1 <= d < C2` | `development` | Kc initial + `(d - C1) / L2` x (Kc mid - Kc initial) |
| `C2 <= d < C3` | `mid` | Kc mid |
| `C3 <= d <= L` | `late` | Kc mid + `(d - C3) / L4` x (Kc end - Kc mid) |
| `d > L` | `after_cycle` | Kc end |

`L2` and `L4` are the lengths of the development and late stages. The curve is continuous: `d = C1` gives Kc initial, `d = C2` gives Kc mid, `d = C3` gives Kc mid, `d = L` gives Kc end, and after the cycle Kc stays at Kc end (judgment log, entry 5).

Warnings from the first plan day `d1` (2.2): `d1 > L` gives `planting_date_past_cycle` with `days_past_cycle = d1 - L`. `d1 < 0` gives `planting_date_in_future` with `days_until_planting = -d1`. The warnings look at the first day only. A plan that crosses a boundary later (for example the last cycle day inside the plan) has no warning, and its days carry the right `stage`.

Boundary values (each is a test, 5.3; Kc to 6 decimals):

| Crop | `d` | `stage` | `kc` |
|---|---|---|---|
| tomato | -1 | initial | 0.6, warning `planting_date_in_future` (1 day) |
| tomato | 0, 29 | initial | 0.6 |
| tomato | 30 | development | 0.6 (first development day) |
| tomato | 31 | development | 0.61375 |
| tomato | 69 | development | 1.13625 (last development day) |
| tomato | 70 | mid | 1.15 (first mid day) |
| tomato | 114 | mid | 1.15 (last mid day) |
| tomato | 115 | late | 1.15 (first late day) |
| tomato | 116 | late | 1.138333 |
| tomato | 144 | late | 0.811667 |
| tomato | 145 | late | 0.80 (last cycle day) |
| tomato | 146 | after_cycle | 0.80, warning `planting_date_past_cycle` (1 day) if it is the first plan day |
| bell-pepper | 29, 30 | initial, development | 0.6, 0.6 |
| bell-pepper | 64, 65 | development, mid | 1.037143, 1.05 |
| bell-pepper | 104, 105, 106 | mid, late, late | 1.05, 1.05, 1.0425 |
| bell-pepper | 125, 126 | late, after_cycle | 0.90, 0.90 |

## 3.3 TAW, ETc, p and RAW

For each plan day:
- `TAW = available_water_mm_per_m x Zr` (mm). It is the same for every day of the plan (Eq. 82, judgment log, entry 6).
- `ETc = Kc x ET0` (mm/day), the single crop coefficient approach (Eq. 58).
- `p = clamp(p_table + 0.04 x (5 - ETc), 0.1, 0.8)` (judgment log, entry 1).
- `RAW = p x TAW`. The trigger level of the bucket is `TAW - RAW`.

## 3.4 The daily step

The state is the depletion `D` at the end of the previous day (mm of water missing from the bucket, 0 at field capacity). Day 1 starts from `D = RAW` of day 1 (judgment log, entry 2). For each weather row, in order:

1. `d`, stage and `Kc` (3.2), `ETc`, `p` and `RAW` (3.3).
2. **Rain counted:** `rain_counted = 0` if `rain_mm < 0.2 x ET0`, otherwise `rain_mm` (judgment log, entry 3). Rain exactly at the threshold counts. If ET0 is 0, any rain counts.
3. **Depletion before irrigation:** `before = min(TAW, max(0, D + ETc - rain_counted))`. A negative value means the rain was more than the bucket could hold, and the excess is lost as deep percolation and not carried (Eq. 85, 86 and 88). The upper limit `TAW` is Eq. 86. The crop cannot take more water than the root zone holds.
4. **Irrigation:** `need = max(0, before - RAW)`. `irrigation = min(need, cap_mm)`, where `cap_mm` is the depth that 1440 minutes of running gives (3.5). `capped` is true when `need > cap_mm`.
5. **End of day:** `D = before - irrigation`. `bucket_mm = TAW - D` and `trigger_mm = TAW - RAW`.

`Ks` (FAO Eq. 84) is **not** used: the plan always uses `ETc` and never the reduced ET of a stressed crop (my call, below). Nothing in the plan depends on the soil's real water content except through this model.

My call on Ks: after a capped day, `D` can be above RAW, and FAO would then reduce the crop's ET by `Ks`. The planner does not, for two reasons. It plans the water the crop needs at standard conditions, so a smaller number on a stressed day would give less water to a crop that is already short. And the day with `D > RAW` is visible in the plan (`bucket_mm` below `trigger_mm`, `capped: true`), so nothing is hidden. It is a limitation (3.8).

## 3.5 The 1440-minute cap

`application rate = emitter flow_lph / (row_spacing_m x emitter_spacing_m)` (mm/h; litres per hour per m²). `cap_mm = 24 x application rate`, which is 1440 minutes of running. The cap is a safety net against a plan that asks for more than a day of running (judgment log, entry 2). With the seed plots it never applies, because they apply 1.0 to 5.6 mm/h, so 24 to 133 mm a day. It applies only to a plot whose emitters apply less than ETc over 24 hours. A capped day gives `run_minutes: 1440`, `capped: true`, and the remaining depletion stays in `D` for the next day.

## 3.6 Litres and minutes

- `emitters = area_m2 / (row_spacing_m x emitter_spacing_m)`, not rounded (the task's example uses 1666.67 emitters).
- `flow_lph = emitters x emitter flow_lph` (the top-level field).
- `litres = irrigation x area_m2` (1 mm over 1 m² is 1 litre).
- `run_minutes = litres / flow_lph x 60`.

Check with the task's example: mid-season tomato, ET0 6.0 mm, no rain, 1000 m², rows 1.5 m, emitters every 0.4 m at 1.0 L/h. `ETc = 1.15 x 6.0 = 6.9 mm`, `p = 0.40 + 0.04 x (5 - 6.9) = 0.324`, and with the day-1 start `D = RAW`, the overshoot is `6.9` mm. `litres = 6900`, `flow_lph = 1666.67`, `run_minutes = 6900 / 1666.67 x 60 = 248.4`, shown as 248.

## 3.7 Rounding

Done once, when the engine's result is turned into the JSON of 2.2, in a function of its own and never inside the engine. Ties round half up. The rules are in 2.2: `kc` 3 decimals, mm and `flow_lph` 2 decimals, `litres` and `run_minutes` whole numbers each from full precision, at least 1 minute when `irrigation_mm` is above 0, and `bucket_mm` and `trigger_mm` rounded from their own full-precision values.

## 3.8 Very small irrigations: keep them

After rain, a day can cross the trigger by a tiny overshoot. Example (North block, ETc 5, `p = 0.40`, `RAW = 49`): rain has left `D = 44.3`. The day gives `before = 44.3 + 5 = 49.3`, so `irrigation = 0.3 mm`, 300 L and `300 / 1666.67 x 60 = 10.8`, shown as 11 minutes. The next day gives `before = 49 + 5 = 54`, so `irrigation = 5 mm`, 5000 L and 180 minutes.

| | Day N | Day N+1 | Two days together |
|---|---|---|---|
| **A: keep (the rule as written)** | 0.3 mm, 300 L, 11 min | 5.0 mm, 5000 L, 180 min | 5300 L, 191 min |
| **B: minimum dose of 1 mm, the rest carried** | 0 mm, bucket 73.2 mm (trigger 73.5) | 5.3 mm, 5300 L, 191 min | 5300 L, 191 min |

The total is the same, and only the timing of 300 L moves by one day. Under B the crop sits 0.3 mm beyond the no-stress limit for a day (`Ks = 0.996` by FAO's formula, a loss of 0.4 percent of ET). A small dose happens only on the first day a rain episode ends, and after it the plan irrigates the full ETc every day, so there is at most one short run per rain episode.

**Chosen: A, keep.** The rule stays one line, every number can be traced, and no new constant is invented (B needs a threshold with no source, like the haircut rejected in judgment log entry 3, and it turns the one-line rule into a rule with a carry). The cost is a run of a few minutes after a rain, which the README names as a limitation. Raising the trigger to a margin of RAW is the same kind of change, and it is a non-goal (1.3). It is recorded as judgment log entry 10.

## 3.9 Limitations (README and judgment log)

- No adjustment of Kc for wind or humidity (FAO Eq. 62 and 65 need wind and minimum humidity, and weather gives only ET0 and rain). Table values stand for a standard climate.
- Kc initial is the table value for typical wetting, with no adjustment for frequent wetting or for the wetted fraction of drip (Eq. 60).
- One row of Table 11 per crop, whatever the planting season, and a fixed root depth at the Table 22 minimum.
- A young plant has shallower roots than the fixed depth, so in the first weeks the bucket is overestimated. In dry weather the daily dose is unchanged, but after heavy rain early in the season the plan can skip irrigation too long. A growing root depth (FAO-56 Annex 8, Eq. 8-1) is a possible later improvement (judgment log, entry 6).
- Rain is a forecast. Runoff is 0. The threshold of 0.2 x ET0 is a rule of thumb, so the result jumps at it.
- The start level is an assumption (`assumed_start`). There is no margin for forecast error and no memory of missed irrigations.
- `Ks` is not used. After a capped day the crop can be below the no-stress limit, and the plan shows it (`bucket_mm` below `trigger_mm`).
- Very small irrigations are kept (3.8).
- After the end of the crop cycle Kc is held at Kc end, with a warning (judgment log, entry 5).

## 3.10 The engine's interface

One function takes the inputs of 3.1 and returns, for each weather row, the values of the day in full precision (`d`, `stage`, `kc`, `etc`, `p`, `raw`, `rain_counted`, `irrigation`, `capped`, `litres`, `run_minutes`, `depletion`, `bucket`, `trigger`), together with `taw`, `flow_lph`, the start bucket and the warnings. It raises `ValueError` for an input that breaks its rules: a non-positive area, spacing, flow or soil value, a non-finite or negative ET0 or rain, an unknown crop, or weather dates that are not consecutive (each date exactly one day after the previous one, so a gap, a repeated date and a wrong order are all errors, because the depletion is carried from day to day). The service checks what it receives from registry and weather before it calls the engine and answers 503 naming that service (4.4), so a `ValueError` that still reaches the service means a bug or an unknown crop, and it is an unexpected error: 500 `UNAVAILABLE` (2.3). The engine does not know about HTTP, JSON or the other services.

---

# Part 4. The upstream calls and settings

## 4.1 What one request does

The planner is stateless: it keeps nothing between requests and calls registry and weather every time (weather has its own cache). After `days` is validated (2.1), and with no upstream call before that:

1. `GET {REGISTRY_BASE_URL}/v1/plots/{plot_id}` (the id percent-encoded). The answer gives `crop_id`, `planting_date`, `area_m2`, `row_spacing_m`, `emitter_spacing_m`, `soil_id`, `emitter_id`, `lat` and `lon`.
2. In parallel:
   - `GET {REGISTRY_BASE_URL}/v1/soils/{soil_id}` for `available_water_mm_per_m`,
   - `GET {REGISTRY_BASE_URL}/v1/emitters/{emitter_id}` for `flow_lph`,
   - `GET {WEATHER_BASE_URL}/v1/forecast?lat={lat}&lon={lon}&days={days}`, with the plot's `lat` and `lon` as registry gave them (written with Python's shortest decimal text, which matches weather's accepted forms) and the `days` of the request. `crop_id` needs no call, because the crop table is in the engine.
3. The first failure wins: the other calls of step 2 are cancelled, and the answer is the one in 4.3. No partial plan is ever returned.
4. The answers are checked (4.4), the engine runs (Part 3), and the result is rounded into the JSON of 2.2.

The planner sends no credentials and no cookies. Its calls carry nothing about the grower.

## 4.2 Settings (`.env`, read by pydantic-settings in `config.py`)

| Variable | Default | Rule |
|---|---|---|
| `REGISTRY_BASE_URL` | none, **required**, for example `http://127.0.0.1:8000` | `http://` or `https://` URL with a host, and no user info, query or fragment. A trailing `/` is removed |
| `WEATHER_BASE_URL` | none, **required**, for example `http://127.0.0.1:8001` | same rule |
| `REGISTRY_TIMEOUT_SECONDS` | 2 | number above 0 and at most 30 |
| `REGISTRY_RETRIES` | 1 | whole number 0 to 5 |
| `WEATHER_TIMEOUT_SECONDS` | 12 | number above 0 and at most 240 |
| `WEATHER_RETRIES` | 0 | whole number 0 to 5 |
| `RETRY_DELAY_SECONDS` | 0.3 | number 0 to 10 |

- Both base URLs have no default on purpose: a missing `.env` must stop the service, not make it call a guessed address.
- The `.env` file is found next to `config.py`, not in the working directory. A real environment variable wins over `.env`, even an empty one. An empty value is invalid for every variable, a number and a URL alike.
- A missing or invalid variable stops startup with an error that names every bad variable and the rule it broke, for example `REGISTRY_BASE_URL: required`. The error never shows a value. The settings' `repr` does not show the two URLs.
- `.env.example` is committed with every variable of this table, placeholders only, and a comment on each. A test checks that every setting in `Settings` appears in `.env.example` and the other way round.
- The port is not a setting. The service starts with `uv run uvicorn main:app --host 127.0.0.1 --port 8002`. The planner keeps no state, so more than one worker is fine.

**The worst-case wait.** Let `A = (REGISTRY_RETRIES + 1) x REGISTRY_TIMEOUT_SECONDS + REGISTRY_RETRIES x RETRY_DELAY_SECONDS` (the longest a registry call can take) and `B = (WEATHER_RETRIES + 1) x WEATHER_TIMEOUT_SECONDS + WEATHER_RETRIES x RETRY_DELAY_SECONDS`. The plot call comes first, and the three calls of step 2 run in parallel, so the longest a plan request can wait is `A + max(A, B)`. With the defaults `A = 2 x 2 + 0.3 = 4.3 s` and `B = 12 s`, so **16.3 s**. With the largest allowed values `A = 6 x 30 + 5 x 10 = 230 s` and `B = 6 x 240 + 5 x 10 = 1490 s`, so 1720 s. The README states the formula, the default and the maximum.

Why these defaults (judgment log, entry 9): weather already makes up to 3 attempts of 3 s (10 s worst case with its defaults) and keeps a per-cell cool-down, so the planner gives it a little more than that (12 s) and does not retry. A retry on top would multiply the wait, and during an outage it would meet the cool-down anyway. The README says: if you raise weather's timeout or retries, raise `WEATHER_TIMEOUT_SECONDS` above weather's worst case. Registry is a database read, so a short timeout with one retry covers a dropped connection without a long wait.

## 4.3 Waiting, retrying and failing

- One shared `httpx.AsyncClient` for registry and one for weather, created at startup and closed at shutdown. Redirects are not followed (a redirect status is a failure). TLS verification stays on.
- **Every attempt has a hard total deadline** (`REGISTRY_TIMEOUT_SECONDS` or `WEATHER_TIMEOUT_SECONDS`) around the whole call, from the request to the last byte of the body, including waiting for a free connection and connecting. It is applied around the call itself and is not left to httpx's per-phase timeouts, so a full pool or a slow trickle cannot stretch the wait, and the worst case above holds under load.
- Between attempts the planner waits `RETRY_DELAY_SECONDS`, through an injected `sleep` (tests use a fake one). There is no wait after the last attempt. The planner reads no clock otherwise: its days come from weather's rows.
- **Registry** is retried on a timeout, a transport error and a 5xx. It is not retried on a 404 (an answer) or on any other 4xx (our request is wrong, and a retry will not help).
- **Weather** is retried on every failure, up to `WEATHER_RETRIES` (default 0), with the same delay.
- A thrown error inside an attempt counts as a failed attempt. An unexpected exception is logged by class only (4.5).

The answer when a call ends in failure:

| Case | Answer |
|---|---|
| Plot call: 404 | 404 `NOT_FOUND`, detail `Plot not found`. No other call is made |
| Plot call: timeout, transport error, 5xx or another 4xx, after the retries; or an invalid body (4.4) | 503 `UPSTREAM_UNAVAILABLE`, detail `registry-service unavailable` |
| Soil or emitter call: any failure, **including a 404** (the plot refers to a soil or emitter the catalogue does not have, which is registry data that does not agree with itself); or an invalid body | the same 503 naming registry |
| Weather call: timeout, transport error, any non-200 status (its own 503 and 500 included), or an invalid body (4.4) | 503 `UPSTREAM_UNAVAILABLE`, detail `weather-service unavailable` |
| An unexpected exception anywhere else, or a `ValueError` from the engine (3.10), or an unknown `crop_id` | 500 `UNAVAILABLE`, fixed detail, no `Retry-After` |

`Retry-After` on a 503: the upstream's `Retry-After` of the failing answer if it is a whole number from 1 to 60 (registry sends 5 for a database failure, weather sends the rest of its cool-down), otherwise 5. When the call failed without an answer (timeout, transport error, invalid body) it is 5.

A fresh weather answer, a stale weather answer and a short one are all successes here (2.2): `stale` and `forecast_short` carry the difference. Only an answer that fails 4.4 is a failure.

## 4.4 What counts as a valid upstream answer

An answer is used only if all of this holds. Otherwise it is a failed attempt of that service, and nothing from it reaches the plan. The checks are made on the decoded JSON, in `upstream.py`, before the engine is called (the engine checks again, 3.10).

**Plot** (registry): status 200, a JSON object with:
- `crop_id`, `soil_id` and `emitter_id`: non-empty text;
- `planting_date`: a valid `YYYY-MM-DD` date;
- `area_m2`, `row_spacing_m`, `emitter_spacing_m`: real numbers (an integer or a float, not a boolean, not a string, not `null`), finite and above 0;
- `lat` between -90 and 90 and `lon` between -180 and 180: real numbers, finite.

**Soil:** status 200, an object whose `available_water_mm_per_m` is a real number, finite and above 0. **Emitter:** status 200, an object whose `flow_lph` is a real number, finite and above 0.

**Forecast** (weather): status 200, a JSON object with:
- `stale`: a boolean; `source`: the text `open-meteo`; `fetched_at`: a valid UTC time ending in `Z`;
- `days`: a list of 1 to `days` rows (fewer than asked is fine, none or more than asked is not), each an object with a valid `YYYY-MM-DD` `date`, and `et0_mm` and `rain_mm` real numbers (not boolean, not string, not `null`), finite and not negative;
- the dates are **consecutive**: each is exactly one day after the previous one.

A single bad value rejects the whole answer. There is no partial use, no zero for a missing value and no default for a missing day. Extra fields are ignored. The planner does not check that the first date is today: it has no clock for that, and weather guarantees it (weather-service entry 1). Plan dates are always weather's dates.

## 4.5 Logging and secrets

The bar is weather-service's. The planner holds no secret, but its logs must not carry a URL, a plot id, a response body or an exception message, because they could carry data of a grower or of another service.
- The `httpx` and `httpcore` loggers are set to WARNING at startup (httpx logs request URLs at INFO).
- One WARNING per failed attempt of the client: the service name (`registry-service` or `weather-service`), the attempt number and a kind: `timeout`, `transport`, `status <code>`, or `not_json`. An invalid answer (4.4) is checked after the client has returned, so it has no attempt line.
- One WARNING when a request ends in a 503, with the service name and the kind. For an invalid answer the kind is `invalid` plus the rule of 4.4 that failed (for example `weather-service unavailable: invalid dates not consecutive`).
- An unexpected exception is logged by its class only, never its message.
- Translated failures are raised after their `except` block ends, so no httpx exception (whose message can hold the URL) stays in the `__context__` of anything that escapes.
- Nothing else is logged on the request path.
- The settings' `repr` shows no URL (4.2).

---

# Part 5. Build and test

## 5.1 Approaches considered

- **A. A pure engine module, with a thin async service around it (chosen).** The engine holds every formula and constant and knows nothing else. The service validates, calls the upstreams, checks their answers, runs the engine and rounds. A formula can be checked by hand against a unit test, and the engine can become the knowledge skill `irrigation-calc-reference` without a rewrite.
- **B. The formulas inside the route handler.** Rejected: nothing can be tested or reviewed without HTTP and fake upstreams, and the rules cannot be lifted into a skill.
- **C. The engine as a shared package used by several services.** Rejected: the task keeps the services separate (this service imports nothing from the others), and a package for one caller is machinery with no second user.

Also rejected by the task: any AI model computing or adjusting a number of the plan.

## 5.2 Layout

`services/planner-service/`, flat modules like the other two services.

| File | Responsibility |
|---|---|
| `engine.py` | the pure engine of Part 3: crop constants, stages, Kc, p, the daily step, litres and minutes. Standard library only. No network, no clock, no environment, no settings, no rounding |
| `main.py` | `create_app(settings=None, transport=None, sleep=None)` and `app`; startup loads settings (`ConfigError` stops startup); routes `/v1/plots/{plot_id}/plan` and `/health` |
| `config.py` | `Settings`, `ConfigError`, `load_settings()` |
| `errors.py` | problem+json helpers and handlers (own copy of the registry's style) |
| `request.py` | the check of `days` and of the plot id (2.1), on the raw query string |
| `upstream.py` | the two clients, the retry loop with the hard deadline, the checks of 4.4, the failure kinds and the translation to the answers of 4.3 |
| `planner.py` | the orchestration of 4.1: calls `upstream.py`, then `engine.py`, then `output.py` |
| `output.py` | the rounding of 3.7 and the JSON models of 2.2 |
| `clock.py` | the `sleep` used between retries (real in production, fake in tests) |
| `tests/` | see 5.3 |
| `README.md`, `.env.example`, `pyproject.toml`, `uv.lock` | |
| `.claude/skills/irrigation-calc-reference/SKILL.md` | the knowledge skill, written last (5.6). Placed here like the registry's skill under `services/registry-service/.claude/skills` (my call) |

Dependencies: `fastapi~=0.115`, `uvicorn~=0.32`, `httpx~=0.28` (runtime), `pydantic-settings~=2.16`; dev: `pytest~=9.2`. No `tzdata`: the planner handles dates only, and no time zones.

Run, from `services/planner-service`: `uv run uvicorn main:app --host 127.0.0.1 --port 8002`. A real plan needs registry on port 8000 and weather on port 8001.

## 5.3 Tests

No test in the default run touches the real network. The clients run against `httpx.MockTransport`, and `sleep` is fake. Groups:

- **Engine, Kc and stages (3.2):** every row of the boundary table, for both crops. A planting date in the future gives `initial`, Kc initial and the right `days_until_planting` through the service. A cycle that ends inside the plan (the last cycle day, then `after_cycle`) has no warning when the first day is inside the cycle.
- **Engine, the daily step (3.4):**
  - `p` follows the formula, and the limits 0.1 and 0.8 bind (an ETc far above and far below 5);
  - the rain threshold: just below `0.2 x ET0` counts as 0, exactly at it counts, and with ET0 = 0 any rain counts;
  - `before` is clamped at 0 (rain bigger than the bucket, the excess is not carried) and at TAW (a plot with a tiny emitter flow, so the cap keeps binding);
  - the start at `RAW`, the irrigation of only the overshoot, `bucket_mm = trigger_mm` on an uncapped irrigated day;
  - the cap: a plot with an application rate under ETc / 24 h gives 1440 minutes, `capped: true`, and the depletion carried to the next day;
  - Ks is not used: after a capped day ETc is still `Kc x ET0`.
- **Engine, input errors:** `ValueError` for each rule of 3.10, one case each: a non-positive area, row spacing, emitter spacing, flow and soil value, a non-finite and a negative ET0 and rain, an unknown crop, an empty row list, and weather dates with **a gap**, **a repeated date** and **a wrong order**.
- **The three hand-calculated cases (5.4):** each is an engine test with every intermediate value, and they are copied into the knowledge skill.
- **Request check (2.1):** one parametrized case per row of the `days` table, every rejected case is problem+json `VALIDATION` and causes no upstream call. The plot-id guard: 65 characters and a NUL give 404 without a registry call.
- **Settings:** one parametrized case per row of the table below, and the defaults. Every rejected case stops startup with an error that names the variable and the rule and shows no value (a marker value in the URL cases checks that).
- **Upstream checks (4.4):** a valid answer for each of the four calls, and every failure kind one by one (status, not JSON, not an object, a missing field, `null`, a string, a boolean, `NaN`, negative or zero where it must be positive, a bad date, a date gap and a repeated date in the forecast, 0 rows, more rows than asked, `source` not `open-meteo`, `stale` not a boolean, a redirect, a timeout, a transport error, and a client that blocks before connecting and never returns). None may produce a 200. The blocking client must still fail the attempt inside the deadline, and a whole cycle must end within `(retries + 1) x timeout + retries x delay` plus a small margin (a timeout of about 0.05 s).
- **Retry rules (4.3):** registry 5xx, timeout and transport error are retried and a later success gives a plan; a registry 404 and another 4xx are not retried; weather is not retried with the default, and is retried up to `WEATHER_RETRIES` when set; the delay goes through the fake `sleep`.
- **Service flows (fake upstreams):**
  - a fresh plan, a stale plan (every day `stale: true`) and a short plan (a `forecast_short` warning, no padding);
  - 404 for an unknown plot, with no weather call;
  - 503 naming registry for each registry failure, 503 naming weather for each weather failure, and `Retry-After` taken from the upstream answer (1 to 60) or 5;
  - the first failure wins and the other calls of step 2 are cancelled;
  - a soil or emitter 404 gives the 503 naming registry;
  - `planting_date_past_cycle` and `planting_date_in_future` with their numbers.
- **Contract:** the exact set of keys at the top level, in a day and in a warning; rounding as in 2.2 (a tie rounds half up, `kc` 3 decimals, whole litres and minutes, at least 1 minute for an irrigation above 0, `run_minutes: 0` only when `irrigation_mm` is 0); `fetched_at` is weather's; `et0_mm` and `rain_mm` equal weather's. Every failure test checks the answer is a 503, never a 200 with made-up numbers. A test produces the README's example (the North block, 2026-11-17) from the fake upstreams and checks it equals the JSON in the README text.
- **Errors and health:** 404 for an unknown route and 405 for a wrong method, with their codes and the problem+json shape. An unexpected exception inside the route returns 500 `UNAVAILABLE` with the fixed detail, no `Retry-After`, and a marker secret in the exception message is in neither the body nor the log. `GET /health` answers `{"status": "ok"}` and makes zero upstream calls, also while both upstreams fail.
- **Logging and secrets (4.5):** with every logger at DEBUG, no log record holds a URL, a plot id, a response body or an exception message (marker values in each); a failed attempt logs the service name, the attempt number and the kind; `httpx` and `httpcore` are at WARNING; no exception chain that escapes holds an httpx exception; the settings `repr` shows no URL.
- **Rules about the code:** a test that fails if any module refers to `services/registry-service` or `services/weather-service`, and one that fails if `engine.py` imports anything outside the standard library, or imports `time`, `os`, `random`, `httpx` or `fastapi`, or calls `date.today()` or `datetime.now()`, or reads the environment. The engine may use `datetime.date` and `timedelta` for date arithmetic.

**Settings table** (one parametrized case per row):

| Variable | Accepted | Rejected |
|---|---|---|
| `REGISTRY_BASE_URL`, `WEATHER_BASE_URL` | `http://127.0.0.1:8000`, `https://example.com/api`, `http://localhost:8001/` (the trailing `/` is removed) | missing, empty, `ftp://example.com`, `example.com`, `https://`, `http://user:pw@example.com`, `http://example.com/x?a=1`, `http://example.com/x#f` |
| `REGISTRY_TIMEOUT_SECONDS` | `0.1`, `2`, `30` | `0`, `-1`, `30.1`, `abc`, `nan`, `inf`, empty |
| `REGISTRY_RETRIES`, `WEATHER_RETRIES` | `0`, `1`, `5` | `-1`, `6`, `1.5`, `abc`, empty |
| `WEATHER_TIMEOUT_SECONDS` | `0.1`, `12`, `240` | `0`, `-1`, `240.1`, `abc`, `nan`, `inf`, empty |
| `RETRY_DELAY_SECONDS` | `0`, `0.3`, `10` | `-0.1`, `10.1`, `abc`, `nan`, empty |

The defaults are checked too: with only the two URLs set, the settings equal the table in 4.2. Every test that guards one of these rules must be shown to fail once, by removing the guarded behaviour on purpose, and then restored (the practice used for the registry and the weather service).

## 5.4 The three hand-calculated cases

All three are checked by an independent calculation. Each is an engine test, and each goes into the knowledge skill later with its inputs, its intermediate values and its result. Day numbers use the planting date as day 0 (3.2). Floating-point results are compared with a tolerance.

**Case (a): the task's example.** Tomato, planted 2026-03-01, loam (175 mm/m), 1000 m², rows 1.5 m, emitters every 0.4 m at 1.0 L/h. One day: 2026-06-09, ET0 6.0 mm, rain 0.

| Step | Value |
|---|---|
| `d`, stage | 100, mid |
| Kc | 1.15 |
| ETc | 1.15 x 6.0 = 6.9 mm |
| TAW | 175 x 0.7 = 122.5 mm |
| p | 0.40 + 0.04 x (5 - 6.9) = 0.324 |
| RAW | 0.324 x 122.5 = 39.69 mm; start `D` = 39.69 |
| before | 39.69 + 6.9 = 46.59 mm; need = 46.59 - 39.69 = 6.9 mm |
| litres | 6.9 x 1000 = **6900 L** |
| flow | 1000 / (1.5 x 0.4) x 1.0 = 1666.67 L/h |
| minutes | 6900 / 1666.67 x 60 = 248.4, shown as **248** |
| end of day | `D` = 39.69; bucket = 82.81 mm = trigger 82.81 mm |

**Case (b): rain, skipped days and a small irrigation.** The North block (same plot as (a)), five days from 2026-08-10 (`d` = 162 to 166, `after_cycle`, Kc 0.8). ET0 is 6.25 mm every day, so ETc = 0.8 x 6.25 = 5.0 mm, `p` = 0.40 and RAW = 49.0 mm every day. The rain threshold is 0.2 x 6.25 = 1.25 mm. The start is `D` = 49.0.

| Day | Rain (mm) | Counted | before (mm) | Irrigation | Litres, minutes | Bucket / trigger (mm) |
|---|---|---|---|---|---|---|
| 1, 08-10 | 0 | 0 | 49 + 5 = 54 | 5.0 mm | 5000 L, 180 | 73.5 / 73.5 |
| 2, 08-11 | 19.7 | 19.7 | 49 + 5 - 19.7 = 34.3 | none | 0 L, 0 | 88.2 / 73.5 |
| 3, 08-12 | 0.5 | 0 (below 1.25) | 34.3 + 5 = 39.3 | none | 0 L, 0 | 83.2 / 73.5 |
| 4, 08-13 | 0 | 0 | 39.3 + 5 = 44.3 | none | 0 L, 0 | 78.2 / 73.5 |
| 5, 08-14 | 0 | 0 | 44.3 + 5 = 49.3 | 0.3 mm | 300 L, 10.8 shown as 11 | 73.5 / 73.5 |

The case covers the start at the trigger, an irrigated day, a rain day, the small-rain rule, two dry days that cross nothing, and a small irrigation of 0.3 mm (judgment log, entry 10).

**Case (c): a bell pepper in the development stage, other soil and emitter.** East block: bell pepper, planted 2026-04-12, clay loam (200 mm/m), 800 m², rows 1.5 m, emitters every 0.4 m at 1.6 L/h. Two days from 2026-06-01, ET0 5.6 mm, no rain.

| Step | Day 1 (`d` = 50) | Day 2 (`d` = 51) |
|---|---|---|
| Stage | development | development |
| Kc | 0.6 + (50 - 30) / 35 x (1.05 - 0.6) = 6/7 = 0.857143 | 0.6 + 21 / 35 x 0.45 = 0.87 |
| ETc | 0.857143 x 5.6 = 4.8 mm | 0.87 x 5.6 = 4.872 mm |
| TAW | 200 x 0.5 = 100 mm | 100 mm |
| p | 0.30 + 0.04 x (5 - 4.8) = 0.308 | 0.30 + 0.04 x (5 - 4.872) = 0.30512 |
| RAW | 30.8 mm | 30.512 mm |
| before | start `D` = 30.8, so 30.8 + 4.8 = 35.6 mm | 30.8 + 4.872 = 35.672 mm |
| Irrigation | 35.6 - 30.8 = 4.8 mm | 35.672 - 30.512 = 5.16 mm |
| Litres | 4.8 x 800 = 3840 L | 5.16 x 800 = 4128 L |
| Minutes | flow = 800 / 0.6 x 1.6 = 2133.33 L/h, so 3840 / 2133.33 x 60 = 108.0, shown as 108 | 4128 / 2133.33 x 60 = 116.1, shown as 116 |
| Bucket / trigger | 69.2 / 69.2 mm | 69.488 / 69.488, shown as 69.49 / 69.49 |

The case covers Eq. 66 between 0.6 and 1.05, the `p` adjustment, a different soil and emitter, and the effect of RAW changing from day to day: on day 2 the plan irrigates 5.16 mm, which is more than ETc (4.872 mm), because RAW fell by 0.288 mm.

## 5.5 Order of the work

The plan will take the work in this order, and each step ends with its tests green and, for each guard, shown to fail once by removing the guarded behaviour and then restored:

1. **The engine** (`engine.py`) with the boundary table, the step tests, the input-error tests and the three hand-calculated cases, including the code-rule test that keeps the engine pure.
2. **The request check** (`request.py`): `days` and the plot id.
3. **The settings** (`config.py`, `.env.example`) with the settings table.
4. **The upstream client** (`upstream.py`, `clock.py`) with the checks of 4.4, the retry rules and the deadline.
5. **The service and the API** (`planner.py`, `output.py`, `errors.py`, `main.py`): the flows of 4.1, the rounding, the errors, `/health`, the contract tests.
6. **The tests of secrets and logging, and the code rules** across the service.
7. **The README**: how to run, the settings table, the worst-case wait, the plan JSON example (checked by a test), the field table, the limitations of 3.9, the failure table, the Open-Meteo credit note for the frontend, and the optional Mermaid sequence diagram (frontend, planner, registry, weather and the failure branches).
8. **The knowledge skill `irrigation-calc-reference`**, written from the engine and the three cases of 5.4: the formulas, the units, the constants with their FAO sources, and the three cases as worked examples. It is written last so it describes the code that exists.

What is committed together, before any code, in one commit and only when the user says: this spec, `docs/judgment-log.md`, `CLAUDE.md`, the installed research skill (`.claude/skills/`) and `docs/research/fao56.md`. The code then follows in commits per step.

## 5.6 README commitments

How to run, on port 8002; the settings table; the worst-case wait with its formula and example (16.3 s with the defaults, 1720 s with the largest values); the plan JSON with the field table and units; the rounding rules; the meaning of `stage`, `assumed_start`, `warnings`, `capped`, `bucket_mm` and `trigger_mm`, including that on an irrigated day the bucket sits on the trigger by design; the failure table (404, 422, 503 naming the service, 500); that a stale or short forecast still gives a plan; the limitations of 3.9, each in one line, including that the task's "half" is replaced by FAO's p and why (judgment log, entry 1), and that the fixed root depth overestimates the bucket of a young plant (in dry weather the daily dose is unchanged, after heavy rain early in the season the plan can skip irrigation too long, and a growing root depth is a possible later improvement) (judgment log, entry 6); that the planner holds no state and asks registry and weather on every request; that `PATCH /v1/plots/{id}` in the registry fixes a planting date that is past the cycle; the Open-Meteo credit ("Weather data by Open-Meteo.com", with the link) that a frontend must show next to the plan, because `forecast.source` is `open-meteo`; the test commands.

## 5.7 Calls made by the assistant (to check)

1. Flat modules like the other services, with the split of 5.2 (`request.py`, `upstream.py`, `planner.py`, `output.py`).
2. The knowledge skill goes in `services/planner-service/.claude/skills/irrigation-calc-reference/` (the root `.claude/skills/` holds the research skill).
3. No `tzdata` and no time zone code: dates come as text from weather.
4. The case dates: (a) 2026-06-09, (b) 2026-08-10 to 2026-08-14, (c) 2026-06-01 and 2026-06-02, so that each case falls in the stage it demonstrates. Case (b) uses `after_cycle` days because ETc 5.0 is exact there (0.8 x 6.25).
5. No fake-upstream scripts and no p95 measurement, because the task lists no NFR for the planner. A manual run needs the other two services.
6. The settings' URL rule rejects user info, a query and a fragment (4.2).
7. The README example is checked by a test, so it cannot drift from the code.

## 5.8 Left to the builder

The exact pydantic models and messages, the structure of the fake upstreams and the fake `sleep`, the log format, how the tests run async code, the form of the Mermaid diagram, and `httpx` connection limits (left at the defaults, because the per-attempt deadline covers waiting for a connection).

## 5.9 Open points

None for the user at this time. The calls above are the assistant's, for review.
