# Judgment log

Each entry: what the AI tools suggested or the open question they raised, what I decided, and why.

## 1. Depletion fraction p: FAO-56 per crop with the ETc adjustment, not the task's "half"

- **Suggested:** the task says "when the level would fall below half, irrigate", which is a fixed p of 0.5. The agent offered three options: (A) FAO-56 Table 22 p per crop (tomato 0.40, bell pepper 0.30), adjusted each day by `p = p(Table 22) + 0.04 (5 - ETc)` and limited to 0.1-0.8; (B) the Table 22 value without the adjustment; (C) the fixed half. It recommended A.
- **Decided:** option A. RAW = p x TAW, where p is the crop's Table 22 value adjusted for that day's ETc (mm/day, so ETc = Kc x ET0) and limited to 0.1 <= p <= 0.8. Irrigation is triggered from this RAW. The task's "half" is a simplification that we knowingly replace.
- **Why:** FR-2.11 says the numbers follow our own engine and skill, and FAO-56 Ch. 8 (read on the raw page, http://www.fao.org/4/x0490E/x0490e0e.htm) supports each part of this choice:
  - Table 22 gives sweet peppers (bell) p = 0.30 and tomato p = 0.40, and its footnote 2 says: "The values for p apply for ETc ~ 5 mm/day. The value for p can be adjusted for different ETc according to p = p table 22 + 0.04 (5 - ETc)".
  - The text says: "A value of 0.50 for p is commonly used for many crops." So 0.5 is a general default, not a value for these two crops, and for bell pepper it is well above the 0.30 that FAO lists.
  - The text says: "Often, a constant value is used for p for a specific growing period, rather than varying the value each day." So a constant p is a recognised shortcut. FAO gives the numerical adjustment "for adjusting p for ETc rate", with "the adjusted p limited to 0.1 <= p <= 0.8".
  - FAO also says p is lower at high ETc ("For hot dry weather conditions, where ETc is high, p is 10-25% less than the values presented in Table 22"). Our farms are in a hot, dry climate, so the daily adjustment matters in summer and a constant 0.5 would allow stress when ETc is high.
- **Cost:** the trigger level changes from day to day, so the engine and its hand-calculated cases need the adjustment, and a plan will differ from what the task's "half" example would give. The service README and the knowledge skill state that the task's "half" is not used and why.

## 2. Starting level and irrigation depth: start at the trigger, irrigate only the overshoot, cap at 24 hours

- **Suggested:** the service has no irrigation history, so day 1 needs an assumed bucket level. The agent offered three options: (A) a full bucket, (B) a bucket at the trigger (depletion = RAW), (C) B plus an optional query parameter `depletion_mm`. It recommended B. The depth per irrigation was decided by the user in the same step.
- **Decided:**
  - **Start:** depletion = RAW at the start of day 1. The response states this in a field `assumed_start`.
  - **Depth:** each day, `depletion_before = max(0, depletion_prev + ETc - rain)`. If it exceeds RAW, irrigate the overshoot: net depth = `depletion_before - RAW`, so depletion returns to RAW. The plan never refills to field capacity. RAW is the day's RAW (p changes with ETc, entry 1).
  - **Cap:** `run_minutes` never exceeds 1440 per day. If the rule asks for more, the day is capped at 1440 and the remaining depletion is carried to the next day.
- **Why:** the errors are not symmetric. Assuming a full bucket on a dry soil damages the crop. Assuming the trigger on a full soil costs one unneeded irrigation. Annex 8's refill to field capacity is for surface irrigation. On drip it would be large: for the North block (RAW 49 mm, ETc 5 mm) a day-1 refill is 54 mm, which is 54,000 L and about 32 hours of running. The overshoot rule gives 5 mm, 5000 L and 180 min for the same day. Checked by hand on the North block: the task's example (ET0 6.0 x Kc 1.15 = 6.9 mm) gives 6900 L and 248.4 min, which matches the task's 248. After 60 mm of rain depletion goes to 0 and `run_minutes` is 0.
- **Limitation (stated in the README):** the rule keeps the crop at the edge of the no-stress limit, with no margin for forecast error. A margin could be added later, for example by triggering at 90 percent of RAW.
- **To settle in the spec:** after a capped day, depletion carried to the next day can be above RAW, so the engine must say whether Ks (FAO Eq. 84) then reduces ETc or not.

## 3. Rain in the bucket: the FAO small-rain rule, all other rain counts, no runoff

- **Suggested:** weather gives one `rain_mm` per day, and it is a forecast. The agent offered three options: (A) the FAO-56 Ch. 8 rule (rain below 0.2 x ET0 counts as 0, other rain counts in full), (B) count all rain, (C) A plus a fixed haircut such as 80 percent. It recommended A.
- **Decided:** option A. For each day, if `rain_mm < 0.2 x ET0` of that day, rain counts as 0. Otherwise all of it counts as P, with runoff RO = 0 (Eq. 85). Any excess beyond depletion 0 is lost as deep percolation and is not carried to the next day.
- **Why:** the rule is FAO's own. Ch. 8 says: "Daily precipitation in amounts less than about 0.2 ETo is normally entirely evaporated and can usually be ignored in the water balance calculations especially when the single crop coefficient approach is used". We use the single Kc approach. Option B would let drizzle cancel a watering the soil needs. Option C adds a factor with no source, in an engine whose numbers must all be traceable.
- **Limitations (stated in the README):**
  - The threshold is a rule of thumb ("about"), so the result jumps at the threshold: with ET0 5 mm, 0.9 mm of rain counts as 0 and 1.1 mm counts in full.
  - Rain is a forecast, not a measurement. A forecast that is too wet skips an irrigation the crop needed, and the plan does not hold a margin for that.
  - Runoff is set to 0. Heavy rain on a slope or a sealed soil would run off, and the plan would count it as stored water.

## 4. Stage lengths and Kc values: one fixed reading of Table 11 and Table 12 per crop

- **Suggested:** FAO-56 Table 11 has several rows per crop for different regions and planting dates. The agent offered three options: (A) one fixed row per crop chosen for our climate, (B) a row chosen by planting month, (C) stage lengths stored per plot in the registry. It recommended A.
- **Decided:** option A, with these readings (days: init / dev / mid / late):
  - **Tomato:** the Mediterranean row, 30 / 40 / 45 / 30 = 145 days. Kc ini 0.6 (the Solanaceae group value, because Table 12 has no per-crop value), Kc mid 1.15, **Kc end 0.80**. Table 12 prints Kc end for tomato as a range, 0.70-0.90. We use the midpoint, which is also the value of the Solanaceae group row.
  - **Bell pepper:** the Europe and Mediterranean row, 30 / 35 / 40 / 20 = 125 days. Kc ini 0.6 (group value), Kc mid 1.05, Kc end 0.90. The printed row is "25/30 35 40 20 125". Only 30 sums to the printed total of 125 (25 would give 120), so we read the init length as 30.
  - The staked-crop footnote of Table 12 (higher Kc mid, about 1.15 for pepper and 1.20 for tomato) is not applied, because the registry does not say how a plot is grown.
- **Why:** the farms are at about 31.3°N, 34.8°E, a Mediterranean or arid climate, so these are the nearest rows. One row per crop keeps every number traceable to one printed row, and a hand calculation of any day is easy to repeat. Option B needs rules for choosing a row that we would invent. Option C needs registry changes that are out of scope for this task.
- **Limitations (stated in the README):**
  - The stage lengths are a reading of Table 11 and ignore the planting season. FAO says they vary substantially with region, climate and variety. For example, tomato planted in October or November has 180 days in Table 11, not 145.
  - Kc ini is the table value for typical wetting. FAO says it rises with frequent wetting, and Eq. 60 scales it by the wetted fraction for drip. We do not apply either.
  - Kc is not adjusted for wind or humidity (Eq. 62 and 65), because weather-service gives only ET0 and rain.
- **Consequence:** with these lengths all four seed plots are already past their crop cycle today (2026-11-17). Tomato has 145 days against 261 (North block) and 275 (West block). Bell pepper has 125 days against 200 (Greenhouse) and 219 (East block). So what the planner does after the end of the cycle (entry 5) decides what every demo plan looks like.

## 5. After the end of the crop cycle: hold Kc at Kc end, mark every day with its stage, warn with a code

- **Suggested:** the registry has no harvest date, so the planner cannot tell a harvested plot from a late crop, and all four seed plots are already past their cycle (entry 4). The agent offered three options: (A) hold Kc at Kc end and flag it, (B) assume bare soil with Kc ini and flag it, (C) refuse with a new error code. It recommended A.
- **Decided:**
  - Option A. After the last day of the cycle, Kc stays at the crop's Kc end (tomato 0.80, bell pepper 0.90).
  - **Every** day of the plan carries a `stage` field with one of `initial`, `development`, `mid`, `late`, `after_cycle`, so a reader and the frontend can see why Kc is what it is.
  - The plan has a top-level list `warnings`. Each warning is an object with a stable `code` and its numbers, not free text. For this case: `planting_date_past_cycle` with `days_past_cycle`. The list is empty when there is nothing to warn about.
- **Why:** the errors are not symmetric. Assuming a crop is still standing when it was harvested wastes some water. Assuming it was harvested when it is standing leaves the crop dry. Option B irrigates at a factor that fits no crop. Option C adds an error code the task does not list and would make every seed plot fail in the demo. A code with numbers in `warnings` lets the frontend show the warning in a structured way, and the stage field makes the Kc visible on each row.
- **Cost:** a harvested plot keeps getting a plan until someone fixes the planting date in the registry. `PATCH /plots/{id}` exists, so this needs no code change.

## 6. Root depth: fixed at the Table 22 minimum

- **Suggested:** FAO-56 Table 22 gives a range of root depth per crop (tomato 0.7-1.5 m, bell pepper 0.5-1.0 m). The agent offered three options: (A) fixed at the minimum, (B) growing root depth as in Annex 8 equation 8-1, (C) fixed at the midpoint. It recommended A.
- **Decided:** option A. Zr is fixed for the whole plan: tomato 0.7 m, bell pepper 0.5 m. TAW = `available_water_mm_per_m` of the soil x Zr (Eq. 82, with the registry value equal to (thetaFC - thetaWP) x 1000).
- **Why:** FAO's footnote to Table 22 says: "The smaller values for Zr may be used for irrigation scheduling and the larger values for modeling soil water stress or for rainfed conditions." Option B needs a minimum root depth that FAO gives only for dry beans (Annex 8), so we would invent one for tomato and pepper, and a bucket that changes size complicates the depletion carried from day to day. Option C fits modelling stress better than scheduling. Zr also moves the trigger line in millimetres, because RAW = p x TAW. For the North block (loam, 175 mm per m, p 0.40): Zr 0.7 m gives TAW 122.5 mm and RAW 49 mm, while the midpoint 1.1 m would give TAW 192.5 mm and RAW 77 mm. The minimum Zr, like the per-crop p of entry 1, makes the plan irrigate earlier, which is the cautious side.
- **Costs (stated in the README), two sides:**
  - **Mature crop:** the table gives the maximum effective root depth of a grown crop, and real roots are probably deeper than the minimum of the range. The bucket is then smaller than the real one, so the plan irrigates somewhat earlier and more often than needed, and it gives less credit to heavy rain, so more of it is lost as deep percolation (entry 3). This is the cost of the safe side.
  - **Young plant:** a seedling has much shallower roots than any value in Table 22, so in the first weeks the fixed Zr overestimates the bucket. In dry weather this changes nothing, because the rule irrigates the day's ETc whatever the bucket size (entry 2). After heavy rain early in the season the plan can skip irrigation for longer than a seedling tolerates. Example: roots of 0.1 m, so TAW is 17.5 mm and RAW about 8.75 mm at ETc 2.5 mm per day (p 0.50), and 50 mm of rain on day 1: the seedling needs water again on day 4, while the plan, with Zr 0.7 m (TAW 122.5 mm, RAW about 61 mm), irrigates on none of its 7 days. The effect is limited: it needs heavy rain, it concerns the first weeks (spring planting in this climate is dry), and the planner is recalculated on every request.
  - **A possible later improvement:** a root depth that grows with the crop (FAO-56 Annex 8, Eq. 8-1). It needs a minimum root depth, which FAO gives only for dry beans, so for tomato and pepper we would have to invent one, and a bucket that changes size complicates the depletion carried from day to day.

## 7. The bucket level in the plan is the water in the bucket, with the trigger level beside it

- **Suggested:** the task asks for "the bucket level at the end of the day", and the engine works in depletion (FAO's Dr). The agent offered three options: (A) the water in the bucket, (B) the depletion, (C) both. It recommended A.
- **Decided:** option A. Each day has `bucket_mm = TAW - depletion` and `trigger_mm = TAW - RAW` for that day. The top level has `taw_mm`. All in mm. The engine keeps depletion and converts at the edge of the JSON.
- **Why:** the task speaks of a level that falls, and a higher number meaning a fuller bucket is what a chart or a reader expects. Option B has the opposite direction. Option C holds two numbers that must always agree, for little gain.
- **Note for the README:** `trigger_mm` changes from day to day, because RAW changes with ETc through p (entry 1). On a day with irrigation, the overshoot rule (entry 2) ends the bucket exactly at the trigger, so a chart shows the level sitting on the line. This is the intended behaviour and not a bug.

## 8. The plan JSON: derived fields for hand checks, rounding only at the edge

- **Suggested:** the task leaves the exact plan JSON to us. The agent proposed one example for the North block (all numbers computed by hand from entries 1 to 7) and asked for confirmation.
- **Decided:** the top level has `plot_id`, `crop_id`, `area_m2`, `flow_lph`, `taw_mm`, `assumed_start`, `forecast` (`source`, `fetched_at`), `warnings` and `days`. Each day has `date`, `stage`, `stale`, `et0_mm`, `kc`, `etc_mm`, `rain_mm`, `rain_counted_mm`, `irrigation_mm`, `litres`, `run_minutes`, `capped`, `bucket_mm`, `trigger_mm`. The warning codes are `planting_date_past_cycle` (`days_past_cycle`), `planting_date_in_future` and `forecast_short` (`days_requested`, `days_received`). The engine keeps full precision. Rounding happens only in the JSON: `kc` 3 decimals, every mm value and `flow_lph` 2 decimals, `litres` and `run_minutes` whole numbers, each computed from full precision. A day with irrigation never shows less than 1 minute. `et0_mm` and `rain_mm` are weather's values unchanged.
- **Why:** the derived fields (`etc_mm`, `rain_counted_mm`, `irrigation_mm`, `capped`) let anyone check a day by hand from the row, which the knowledge skill and the hand-calculated cases rely on. Rounding in the engine would make errors accumulate through the bucket. `forecast.source` tells the frontend that the Open-Meteo credit applies.

## 9. Calls to registry and weather: weather gets 12 s and no retries, worst case 16.3 s

- **Suggested:** the task says a service that is down or "doesn't answer in time" gives 503 `UPSTREAM_UNAVAILABLE`, and gives no timeout values. The agent proposed the flow, the settings and the failure table, and the user confirmed them.
- **Decided:**
  - **Flow:** validate `days` (no upstream call), then the plot, then in parallel the soil, the emitter and the forecast for the plot's `lat`/`lon`. The first failure wins and cancels the other calls.
  - **Registry:** timeout 2 s per attempt, 1 retry, delay 0.3 s. It is retried on timeout, transport error and 5xx, not on 404 or other 4xx.
  - **Weather:** timeout **12 s, no retries**. Any error status, an invalid body or an empty `days` list gives 503 `UPSTREAM_UNAVAILABLE` naming weather.
  - **Worst case with the defaults: 16.3 s** = plot 2 x 2 + 0.3 = 4.3 s, then the larger of the parallel calls, which is weather's 12 s. The README states the formula.
  - A 503 carries `Retry-After`: the upstream's value if it is a whole number from 1 to 60, otherwise 5.
  - `GET /health` answers `{"status": "ok"}` and never calls registry or weather. Logs hold only the failure kind and the service name, for example "weather-service timeout", never a URL, a body or an exception message. The `httpx` loggers are at WARNING.
- **Why:** weather already makes up to 3 attempts (10 s worst case by default) and keeps a per-cell cool-down. A planner retry on top would multiply the wait, and during an outage it would meet the cool-down anyway. 12 s is that 10 s plus a margin. Registry is a local database read, so a short timeout with one retry covers a dropped connection without a long wait. A dead weather service must never produce a plan of zeros (FR-2.14), so an invalid or empty answer is a failure like a timeout.
- **Cost:** a plan request can wait up to 16.3 s when weather is failing for the first time in a cool-down period. Later requests in the cool-down get weather's answer at once.

## 10. Very small irrigations are kept, with no minimum dose

- **Suggested:** after rain a day can cross the trigger by a tiny overshoot (North block: 0.3 mm, 300 L, 11 minutes). The agent compared (A) keeping the rule as written with (B) a minimum dose of 1 mm with the depletion carried to the next day. It recommended A.
- **Decided:** option A. Every overshoot above 0 is irrigated, however small. A day with irrigation shows at least 1 minute.
- **Why:** the two options give the same total over two days (5300 L, 191 minutes) and differ only in the timing of 300 L, which B moves by one day. B leaves the crop 0.3 mm beyond the no-stress limit for that day (Ks 0.996, a loss of 0.4 percent of ET). A tiny dose happens only on the first day after a rain episode, because the next day the plan irrigates the full ETc. A keeps the rule to one line that can be checked by hand, and B needs a threshold with no source, like the haircut rejected in entry 3.
- **Cost (stated in the README):** after rain the plan can ask for a run of a few minutes. A margin below RAW (entry 2) or a minimum dose can be added later.

## 11. Day count with the planting date as day 0, and no Ks

- **Suggested:** two points of the engine were left open: how days are counted from the planting date, and what happens when depletion is above RAW after a capped day (FAO's Ks, Eq. 84). The agent proposed a convention and a recommendation for each.
- **Decided:**
  - **Day count:** `d = date - planting_date`, the planting date is day 0, and this is FAO's day number `i` in Eq. 66. Stages: initial `d < C1`, development `C1 <= d < C2`, mid `C2 <= d < C3`, late `C3 <= d <= L`, after_cycle `d > L`, with `C1`, `C2`, `C3` the cumulative stage ends and `L` the cycle length (tomato 30, 70, 115, 145; bell pepper 30, 65, 105, 125). `days_past_cycle = d - L`. Kc is continuous across the boundaries and equals Kc end on day `L`.
  - **Ks:** not used. The plan always uses ETc.
- **Why:** day 0 gives the 116 days of the North block (261 - 145) and makes Eq. 66 apply as printed, so the Kc of each boundary day can be checked against FAO. A boundary day belongs to the later stage, and day `L` is the last cycle day because the interpolation reaches Kc end there. With Ks the plan would give less water on a day when the crop is already short, and the day is visible anyway (`bucket_mm` below `trigger_mm`, `capped: true`).
- **Cost:** the cycle spans `L + 1` calendar days, one more than the length FAO prints, which is far inside the accuracy of Table 11. Stress after a capped day is not reduced in the numbers (README limitation).

## 12. The weather rows are checked twice, and the dates must be consecutive

- **Suggested:** the depletion is carried from day to day, so a gap or a repeated date in the weather rows would silently shift the bucket. The user asked that the engine itself refuses such input, and that the planner checks what it receives before it calls the engine.
- **Decided:** the engine raises `ValueError` when the weather dates are not consecutive (each exactly one day after the previous one), and for the other broken inputs (non-positive area, spacing, flow or soil value, a non-finite or negative ET0 or rain, an unknown crop). The planner checks the weather rows first (finite, non-negative ET0 and rain, valid dates, consecutive dates) and answers 503 `UPSTREAM_UNAVAILABLE` naming weather when they are not. It checks the registry's answers the same way and names the registry. A `ValueError` that still reaches the service is an unexpected error (500 `UNAVAILABLE`).
- **Why:** the service check gives the right answer for bad upstream data (a 503 that names the service that sent it), and the engine check is the second line of defence, so the engine stays safe as the future knowledge skill, outside the service. Weather's own rules already give consecutive dates, so a gap means the contract is broken, and no plan is better than a plan on shifted days.

## 13. The build is 12 small tasks, on Sonnet and Haiku

- **Suggested:** the work could be split into a few large tasks or many small ones. The agent proposed 12 tasks in the order of spec 5.5, each ending with green tests and one commit, and a stronger model for the engine, the retry logic and the orchestration. The user chose cheaper models (below).
- **Decided:** Sonnet for every task except task 3 (tests only), which runs on Haiku. Opus is not used unless the user decides so. If the engine, the retry and deadline logic or the parallel calls get stuck, the work stops and the user decides on a stronger model. Each guard test has its red proof written into the task: a named change to the code that must make a named test fail, after which the change is undone. Only the listed red proofs are run, and the full suite runs once at the end of each task, before the commit.
- **Why:** the user has a limited quota, so the cheapest model that can do each task is used. The expected values are in the spec and the plan, so a mistake shows as a failing test. The engine and the deadline and cancellation code are where a mistake costs most, so a stuck task stops and goes back to the user instead of guessing. 12 small tasks keep each context short.
- **Cost:** a cheaper model may need more rounds on the engine and the deadline code. There are more commits and more hand-offs than with a few large tasks, and the task interfaces must be exact (the plan lists them), or two tasks will disagree about a name.

## 14. The knowledge skill is written last, from the code and the three cases

- **Suggested:** the skill `irrigation-calc-reference` could be written before the engine, as its specification, or after it, as its description. The agent recommended after.
- **Decided:** the skill is the last task. It is written from the engine as built and the three hand-calculated cases of the spec (5.4), in `services/planner-service/.claude/skills/irrigation-calc-reference/`, like the registry's skill.
- **Why:** the spec and the judgment log already hold the decisions, and the three cases are tests by then, so the skill can quote values that a test has checked. A skill written first would describe code that does not exist yet, and would drift from it.
