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
