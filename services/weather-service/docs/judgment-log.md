# Judgment log

Each entry: what the AI tools suggested or the open question they raised, what I decided, and why.

## 1. What "today" means: the local date at the point

- **Suggested:** the open question was what "today" means when a cached forecast fetched at 23:30 is still under 3 hours old at 01:00, but its first day is now yesterday. The agent offered three options: the local date at the point, the UTC date, or the first day of whatever the provider last sent. It recommended the local date.
- **Decided:** today is the local date at the point. A cached forecast is fresh only while it is under 3 hours old and its first row is today at the point. The service never serves a row dated before today, and never labels a row as today when it is not. At local midnight the cell is fetched again even if the data is minutes old.
- **Why:** the planner reads the first row as today's recommendation, and the grower sees it first. A first row dated yesterday is a recommendation for the wrong day, which is the worst kind of error in this system. The UTC date would show yesterday's row for the first hours of the day for a farm east of UTC. "The first day the provider sent" would claim to start today while starting yesterday, for up to 3 hours after midnight. The cost of the local date is at most one extra provider call per cell per day.

## 2. A stale answer may have fewer rows than asked, and the planner must not pad it

- **Suggested:** if the provider is down after midnight, the old forecast of a cell may have fewer days left than requested (6 of 7). The agent offered three options: return the rows we have, return 503, or return the rows plus a field saying how many are missing. It recommended the first.
- **Decided:** return the rows we have, with `stale: true` and a shorter `days` list. A caller must check how many rows it received. The planner-service must plan only the days it has, and must never fill the gap with zeros or defaults.
- **Why:** the planner asks for 7 days by default, so a 503 here would turn a short outage after midnight into a full outage for the main caller, for up to the 24-hour stale cap. Six real days are more useful than none, and nothing is invented (FR-2.6 and FR-2.8). The cost is that every caller must handle a short list, so the planner's behavior is written down now, before the planner exists.

## 3. One fetch per cell at a time; the other requests wait and share its result

- **Suggested:** the open question was what happens when several requests for the same cell arrive at the same moment. The agent offered three options: one fetch per cell with the others waiting and sharing the result, every request fetching on its own, or the first request fetching while the others get the old forecast at once. It recommended the first.
- **Decided:** one fetch per cell at a time. The other requests wait and share its result, including a failure (the same stale answer or the same 503 from one cycle), and nobody retries on their own. The fetch runs as its own task, so a waiter that disconnects does not cancel it for the others, and the cell's in-flight marker is cleared in a `finally` block on success, failure, an unexpected exception and cancellation. The wait is bounded by `.env` settings: every attempt has a hard total deadline that includes waiting for a connection, so the worst case is `(retries + 1) × timeout + retries × delay`, which is 10 s by default and at most 230 s. The README states it. A request that joins a running cycle waits up to that worst case even when a stale forecast exists, because FR-2.6 asks for the retries first.
- **Why:** with one fetch per request, a burst after the 3-hour expiry or after a restart becomes a burst of provider calls, and during an outage every request runs its own three attempts against a provider that is already failing. The third option would label data `stale: true` while the provider is healthy, so the label would mean "a refresh is running" instead of "the provider failed". The cost is that waiters wait as long as the fetch does, and that single flight needs care: the check and the start of the fetch must not have an `await` between them, and the marker must always be cleared, or the cell waits forever.

## 4. A cool-down per cell after a failed refresh

- **Suggested:** during a long outage every request that finds a cell stale would start a new cycle, so every caller would wait the full worst case (about 10 s) and the provider would get three calls per cycle, for as long as the outage lasts. The agent offered a short cool-down per cell after a failed refresh, or no cool-down, exactly as FR-2.6 reads. It recommended the cool-down.
- **Decided:** after a failed cycle the cell has a cool-down, 30 s by default and a `.env` setting (0 turns it off). During it there is no provider call and the answer is immediate: the stale rows, or a 503 whose `Retry-After` is the remaining cool-down rounded up to whole seconds, at least 1. After it, the next request starts a new cycle. A successful fetch clears it. The 24-hour stale cap still applies during it. The cool-down is per cell: no global cool-down for the whole provider. Evicting a cell forgets its cool-down. The clock is injected, so tests use a fake clock.
- **Why:** the first request after a failure pays the worst case, and the rest are fast, so the provider is not hammered and callers are not stuck. A provider outage then costs each cell one slow cycle. The cost is that a recovered provider is noticed up to 30 s late, one more setting, and a little state per cell. A global cool-down would be one switch instead, but it would also stop healthy cells from fetching when only one cell's request is failing, so it is kept out.

## 5. The cache is capped, and the least recently used cell goes first

- **Suggested:** a caller walking through coordinates would create a new cell per request, and there are about 6.5 million possible cells. The agent offered a cap with least-recently-used eviction, no cap, or dropping entries only by age. It recommended the cap, combined with dropping entries older than the stale cap.
- **Decided:** at most 2000 cells (`CACHE_MAX_CELLS`, a `.env` setting), ordered by last use. A cell with a fetch in flight is never evicted, and if every cell is in flight the cache may exceed the cap until some finish. Creating a new entry first drops entries older than the 24-hour stale cap, because they can never be served. Evicting a cell forgets its forecast and its cool-down, so a request for an evicted cell during an outage gets the 503 and never stale rows that were evicted. Per-client rate limiting is out of scope, and a scan still costs one provider call per new cell. This is in the spec and the README.
- **Why:** memory stays at a few MB whatever callers do. Without a cap, memory grows without limit under a coordinate scan, and by age alone it is still unbounded at 10 requests per second. The cost is that an evicted cell loses its stale fallback. Eviction does not limit how often callers can cause provider calls, which is why the README says so.

## 6. How old a stale forecast may be: 24 hours, as a setting

- **Suggested:** the task asks to decide how old a forecast may be before it is not served even as stale. The agent proposed 24 hours.
- **Decided:** 24 hours after the fetch, then 503, as `STALE_MAX_AGE_SECONDS` in `.env` (default 24 hours, never below the freshness time) next to the freshness time. A stale answer is also never served with a row dated before today, and never as an empty list. The README states the cap and the reason in these words: a stale answer usually crosses one local midnight and loses one row, and a daylight-saving shift near midnight can cost two, so a request for up to 5 days is always complete, 6 days usually, and 7 days only while no midnight has passed.
- **Why:** the "today" row of a forecast older than a day is a guess made at least two days ahead, and for irrigation a clear 503, with the caller falling back to its own logic, is safer than yesterday's guess. The wording first said "at most one midnight", and that was wrong around daylight-saving changes, so it was corrected before it reached the README. A test covers the 23-hour day in `Europe/Berlin`.

## 7. Async, in one process, with one forecast service that owns the rules

- **Suggested:** three ways to build it: async FastAPI with one forecast service, plain synchronous FastAPI with threads and locks, or a background refresher that keeps requested cells warm.
- **Decided:** async FastAPI with one forecast service that owns freshness, single flight, the cool-down and eviction, and takes the provider and the clock as arguments. The cache and the cool-down live in the memory of one process, so the README says the service must run with a single worker, on port 8001. Services do not import each other's code: this service has its own copy of the registry's error style.
- **Why:** a request waiting for a shared fetch costs a pending task in the async version, so waiting never slows fresh answers. In the threaded version every waiting request holds a thread (the default pool has 40), so about 100 waiting requests during a 10 s cycle would queue fresh answers behind them, which breaks the 100 ms target exactly when the provider struggles. The background refresher needs a schedule per cell and spends provider calls on cells nobody asks about any more, which FR-2.5 to 2.7 do not need.

## 8. A point becomes a cell by exact decimal rounding, and the request text is strict

- **Suggested:** two things found while checking the design. A cell can be a floor or the nearest 0.1° node. And Python's own parsing hides traps: `float()` accepts `1_0`, non-ASCII digits and `nan`; `Decimal` raises `InvalidOperation` for an exponent of 25 digits, which would be a 500; and with `Decimal`'s default 28-digit precision, the 32-character text `0.049999999999999999999999999999` lands in cell 1 instead of cell 0.
- **Decided:** the cell is the point rounded to the nearest 0.1° (`floor(value × 10 + 0.5)`, ties round up), computed from the decimal text with enough precision to be exact, never from a float. The provider is called at the cell's node, not at the caller's point. `lat` and `lon` accept only ASCII text matching a fixed pattern with an exponent of at most three digits and at most 32 characters, and `days` is one ASCII digit from 1 to 7. The range is checked on the exact decimal value, and any conversion error is a 422. `lat` and `lon` in the answer are the caller's values.
- **Why:** the nearest node keeps every cell inside the valid range with no clamping, makes the cached forecast the same whoever asked first, and sends only a 0.1° position to the provider. Exact arithmetic and strict text stop a wrong cell and a 500 from an odd number. The rules are in a table of accepted and rejected texts, and each row is a test.

## 9. A provider answer is accepted whole or not at all

- **Suggested:** FR-2.6 lists a timeout, an error status, a body that is not JSON and a missing field as failures. The agent added what else counts: the docs do not say whether a daily value can be `null`, a response may have fewer than 7 rows, the units could change, and a response may start on a date that is not today.
- **Decided:** an answer is accepted only if it has status 200, a JSON object, exactly 7 dates (valid, consecutive, the first one today at the point by our clock), exactly 7 ET0 values and 7 precipitation values that are real, finite, non-negative numbers (not `null`, a string or a boolean), units `mm`, and a known time zone (the provider's IANA name, or else its fixed offset). One bad entry rejects the whole answer, so nothing is partly used and no zero or default is ever made up. A first row that is not today counts as a failed attempt. Redirects are not followed.
- **Why:** FR-2.8. A forecast of zeros looks like "no water needed", the worst bug in the system, so every rule prefers a 503 or a shorter stale answer over a plausible invented one. A first row that is not today would be a row labeled as today when it is not (entry 1).

## 10. The API key needs https, and the key never reaches a log or an error

- **Suggested:** the key travels in the query string, so over plain `http` anyone on the network can read it, and `httpx` logs request URLs at INFO. The registry's final review found that secrets leak through `repr`, error text and the exception chain.
- **Decided:** a non-empty `PROVIDER_API_KEY` requires an `https://` `PROVIDER_BASE_URL`, except for a host that is exactly `localhost`, `127.0.0.1` or `::1`, for local fakes. Startup fails like any other bad variable, naming the variable and the rule and showing no value. The key is a `SecretStr`, the `httpx` and `httpcore` loggers are set to WARNING, the code logs failure kinds only and never a URL, request, body or exception message, and failures are raised after their `except` block so no `httpx` exception stays in `__context__`.
- **Why:** the same bar as the registry, applied before the code exists, because a leak found late is expensive. The local-host exception keeps tests and fakes simple without opening the door for a real host.

## 11. `rain_mm` is the provider's `precipitation_sum`

- **Suggested:** the task fixes the field name `rain_mm`, but the provider's `precipitation_sum` is rain, showers and snowfall together, with snow counted as water. The provider also has a rain-only value.
- **Decided:** keep `precipitation_sum`, and keep the field name `rain_mm`. The README says the value includes showers and snow counted as water.
- **Why:** the water that reaches the ground is what matters for irrigation. The name is fixed by the task, so the difference is documented instead of hidden.

## 12. The free API's limits, its non-commercial terms, and the credit

- **Suggested:** the first version of the spec said the docs give no rate limits. The pricing and terms pages do: fewer than 10,000 calls per day, 5,000 per hour and 600 per minute (300,000 per month), counted by IP address and application, with no uptime guarantee. The free API is for non-commercial use only, Open-Meteo may block applications that misuse it, and the data is CC BY 4.0, which requires credit.
- **Decided:** the spec and the README state the limits, the non-commercial condition and the paid-plan host and key. The cell cache is the reason the service fits inside the limits (a cell requested all day costs at most about 9 successful fetches a day). A scan over many new cells can exceed them, and the provider then answers with errors. Every failed attempt is retried and counts against the limit, and the decision of no global circuit breaker stays. The README credits "Weather data by Open-Meteo.com" with a link, and the frontend must show the same credit next to any location where the data is displayed.
- **Why:** a limit that is only discovered in production is an outage. The limits are known now, so they are written down with the design choices that keep the service inside them, and with the ones that do not.

## 13. An error-catching middleware, not an `Exception` handler, answers an unexpected error

- **Suggested:** the usual way is a handler for `Exception`. Starlette runs that handler through its server-error middleware, which sends the 500 and then re-raises the error, so a real server prints the traceback. The other way is a middleware that catches the error itself.
- **Decided:** a small middleware (`UnexpectedErrorMiddleware` in `errors.py`) wraps the app. It logs the exception class only and returns the 500 `UNAVAILABLE` answer itself, without `Retry-After`, and nothing is re-raised. If the response has already started, it sends nothing more. A test uses a client that re-raises server errors and shows that the 500 is the answer.
- **Why:** the re-raised error's traceback holds the exception's message, and a message can hold a secret (a URL with the key in it, for example). With a handler, the log rule "never an exception message" would hold in our code and break in the server's output. The cost is a second place that builds the 500, next to the handlers for the known errors.

## 14. An unexpected exception from the provider is a failed attempt, not a failed cycle

- **Suggested:** the first design said an unexpected exception inside a fetch cycle counts as a failed cycle, so the cool-down starts at once. That skips the retries that FR-2.6 asks for when the provider fails in a way we did not foresee.
- **Decided:** an exception raised by the provider call counts as one failed attempt, like a timeout. It is retried, the log line holds the exception class only (`unexpected RuntimeError`), and the cool-down starts only if all attempts fail. An exception from anywhere else in the cycle (the clock, for example) is not retried: it ends the cycle as failed, the cool-down starts, and the in-flight marker is cleared in a `finally` block. Cancellation is not caught.
- **Why:** FR-2.6 asks for retries on every failure, and one odd error from one attempt should not turn into a 30 s cool-down when the next attempt can work. An error outside the provider call is a bug in our own code, and retrying it would repeat it.
