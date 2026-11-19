# Judgment log

Each entry: what the AI tools suggested or the open question they raised, what I decided, and why.

## 1. The 7-day plan: day cards, not a table

- **Suggested:** the task allows a table or a timeline. Alternatives considered: (A) a table with one row per day and a column for each number, (B) vertical day cards, (C) a horizontal timeline. The agent's pick, accepted: B.
- **Decided:** vertical day cards. Each card has the date, the minutes in large type, the stage, and four facts: what the crop needs, the rain, the water depth and the water volume. Bucket and trigger levels are not shown.
- **Why:** a table with that many numbers needs horizontal scroll at 375 px, and NFR-2.8 forbids it. A timeline has the same problem. The daily minutes jump (88, 142, 51) because the allowed depletion moves with the day's ETc, so the need and the depth in mm sit next to the minutes, and the jumps explain themselves.
- **Cost:** a card is taller than a row, so the 7 days take more scrolling, and days are harder to compare side by side.

## 2. Warnings sit above the numbers they affect

- **Suggested:** alternatives for where to show a warning: (A) as a small note under the plan, (B) as a banner between the recommendation and the plan, or (C) inside each day card. The agent's pick, accepted: B.
- **Decided:** one amber banner directly under the recommendation card, with plain words built from the code and its numbers. Unknown codes and invalid numbers are skipped, never shown raw.
- **Why:** every seed plot has the `planting_date_past_cycle` warning, and it changes how far every number can be trusted. The reader sees it before the plan, and it appears once instead of on every card.
- **Cost:** the banner pushes the plan down a little. Today's recommendation stays first, so NFR-2.8 still holds.

## 3. Errors: the type from the code, the failing service from two fixed details

- **Suggested:** alternatives considered: (A) show the planner's `detail` text, (B) map by status only, (C) map by the problem+json `code` and take the failing service from the fixed `detail` texts.
- **Decided:** option C. The type comes from `code`. For `UPSTREAM_UNAVAILABLE` the service is named only when `detail` is exactly `registry-service unavailable` or `weather-service unavailable`. Any other detail gives "A service is unavailable". A network failure or timeout gives "Planner service is unavailable". A 404 with `NOT_FOUND` gives "Plot not found" and a link home. Everything else gives "Something went wrong".
- **Why:** FR-2.18 asks for what happened, not a stack trace. The planner promises a fixed detail that never holds upstream text, but the frontend does not rely on that: a changed or unexpected text can never reach the screen. The test checks that an unknown detail is not echoed.
- **Cost:** a new planner error text shows as generic until the mapping is updated.

## 4. Dates are formatted from the string, in no time zone

- **Suggested:** the obvious way is `new Date("2026-11-19").toLocaleDateString(...)`. That parses the string as UTC midnight and formats it in the machine's time zone, so it shows the previous day on a machine west of UTC. The agent avoided it from the start, and the user added the requirement for a test.
- **Decided:** split `YYYY-MM-DD` into its parts and use only UTC getters on `Date.UTC(y, m - 1, d)`. An invalid date is shown unchanged.
- **Why:** the planner's dates are plain local dates. A farmer reading "Wed 18 Nov" for a plan that starts on the 19th would water on the wrong day. A test sets the process time zone to four different zones and checks that the day never moves.
- **Cost:** none for the user. The weekday and month names are fixed English.

## 5. Timeouts: the plan waits 25 s

- **Suggested:** the usual default is one short timeout (about 5 s) for every call. The user pointed out that the planner can take 16.3 s.
- **Decided:** plan 25 s, registry 5 s, health 1.5 s, all in `src/lib/config.ts`. The plot page shows a skeleton and "Calculating the plan…" while it waits.
- **Why:** the planner's worst case with its defaults is 16.3 s (README of planner-service), so a 5 s limit would cut a plan that was about to arrive. The extra time covers the planner's limit plus transfer. The health calls are short and run in parallel, so a down service never slows a page by more than 1.5 s.
- **Cost:** if the planner hangs, the user waits up to 25 s before the error card.

## 6. The Open-Meteo credit sits directly under the plan

- **Suggested:** alternatives for the credit: (A) in the footer on every page, (B) directly under the plan, (C) both. The agent's pick, accepted: B.
- **Decided:** "Weather data by Open-Meteo.com", linked to https://open-meteo.com/, right under the day cards. It is not shown on the main page or on an error page.
- **Why:** the licence requires the credit next to the data, and the planner's README says `forecast.source` is `open-meteo` and a frontend must show it next to the plan. A footer is far from the numbers on a long page.
- **Cost:** none. On an error page there is no data, so no credit is needed.

## 7. The status line lives in a template, not in the layout

- **Suggested:** the status line was first put in the root layout, next to the header. Alternatives for keeping it fresh: (A) the layout, (B) `template.tsx`, (C) a client component that calls `router.refresh()` on every navigation.
- **Decided:** option B. The `<main>` wrapper and the status line are in `src/app/template.tsx`. The layout keeps only the page shell and the header.
- **Why:** a layout is not rendered again on client-side navigation, so after a click from the main page to a plot the footer kept the state from the first load and could show a service as up when it was down. A template is given a new key and rendered again on each navigation. The user found this in a manual check.
- **Cost:** the health check runs on every navigation, up to 1.5 s in the Suspense fallback, never blocking the page. A template re-renders when its route segment changes, so a click on "Try again" for the same page is the case to watch. Option C would be more reliable, but it adds a client component.
