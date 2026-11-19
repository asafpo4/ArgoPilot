# AgroPilot frontend: design

## Intent
A grower in the field reads today's irrigation answer on a phone. The frontend is a small Next.js app in `services/frontend` that shows farms, plots and one plot's 7-day plan (FR-2.15 to FR-2.19, NFR-2.8). No other pages or features.

## Constraints
- Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui. Server components only. The browser never calls a service.
- All service calls live in `src/lib/`. URLs come from `REGISTRY_URL`, `WEATHER_URL`, `PLANNER_URL` (`.env.local`). A missing variable fails with a clear message naming it. `.env.example` is committed. `.env.local`, `node_modules`, `.next` are never committed.
- `fetch` with `cache: "no-store"`. Timeouts: plan 25 s (planner worst case is 16.3 s), registry 5 s, health 1.5 s.
- The Open-Meteo credit "Weather data by Open-Meteo.com", linked to https://open-meteo.com/, is shown directly under the plan.
- The frontend-design skill is used for the look.

## Approach
Server-rendered pages with a thin typed client per service in `src/lib/`. Types are written by hand from the planner README. Alternatives rejected: client-side fetching (breaks the "browser never calls services" rule), generated API clients (too heavy for 3 endpoints).

## Pages
**`/`**: one section per farm (plots grouped by `farm_id`). Each plot is a full-width link (at least 48 px) to `/plots/{id}` showing name, crop and area. Empty farm: "No plots yet". No farms: "No farms yet". Registry down: error card.

**`/plots/{id}`**, one column at 375 px, in this order:
1. Compact header: plot name, crop.
2. Recommendation card: "Water for N minutes" or "No irrigation today", with litres and mm under it. A "Stale forecast" badge and the forecast age sit inside it when stale.
3. Warnings banner (amber): plain words from the code and its numbers. `planting_date_past_cycle`, `planting_date_in_future`, `forecast_short`. Unknown codes are skipped, never shown raw.
4. Plan as vertical day cards: weekday and date, minutes in large type, stage label, then ETc need, rain (with "not counted" when `rain_counted_mm` is 0 and `rain_mm` is above 0), depth in mm, litres. "Capped at 24 h" tag when `capped`. Each card carries the stale badge when `stale`. Bucket and trigger are not shown.
5. Credit line.

**Layout footer on every page**: status line with three dots (Registry, Weather, Planner), green up, red down, from `GET /health`, in parallel, never breaks the page.

## Rules added by review
- **Dates**: plan dates are plain `YYYY-MM-DD` strings. They are formatted from the string itself (parsed as UTC parts, formatted with a fixed `UTC` time zone), never through the machine's local time zone. A test covers it, including a case that would shift in a negative-offset zone.
- **Errors**: the type comes from the problem+json `code`. For `UPSTREAM_UNAVAILABLE` the failing service comes only from the two fixed details `registry-service unavailable` and `weather-service unavailable`. Any other detail gives "A service is unavailable". Raw detail text is never shown.
- **Stale age**: the server computes the age from `forecast.fetched_at` ("fetched 20 minutes ago"). No raw UTC timestamp is shown.

## Error cards (plot page)
| Case | Message |
|---|---|
| 503, registry detail | "Registry service is unavailable" + Try again, retry hint from `Retry-After` |
| 503, weather detail | "Weather service is unavailable" + Try again |
| 503, other detail | "A service is unavailable" + Try again |
| 404 `NOT_FOUND` | "Plot not found" + link to `/` |
| network error or timeout | "Planner service is unavailable" + Try again |
| anything else | "Something went wrong. Try again." |

The plot name still shows when the registry answered. Try again is a plain link to the same URL.

## Loading
`loading.tsx` on the plot page: card skeletons and the text "Calculating the plan…".

## Look
Warm off-white background, deep green accent, large type, high contrast, amber for warnings and stale. Not the default shadcn gray.

## Non-goals
Editing plots, forms, auth, charts, caching, client-side state, other pages.

## Left to the builder
Exact fonts, spacing and component choice, within the rules above. Test runner is Vitest, only for the pure helpers (date formatting, age, error mapping, warning text).
