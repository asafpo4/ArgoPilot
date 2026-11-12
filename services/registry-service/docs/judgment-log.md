# Judgment log

Each entry: what the AI tools suggested or the open question they raised, what I decided, and why.

## 1. Where to turn database failures into HTTP 503

- **Suggested:** the agent first planned to put the 503 mapping in `db.py`.
- **Decided:** `db.py` classifies the driver's errors and raises its own `DatabaseUnavailable`. `errors.py` has the exception handler that turns it into 503. `db.py` knows nothing about HTTP.
- **Why:** `db.py` should not know about HTTP status codes. Keeping all error responses in one file means the problem+json format is defined in one place.

## 2. Defaults for the unclear points in the task

- **Suggested:** the agent listed 12 unclear points, each with a default. For example: unknown farm in `?farm_id=` returns `200 []`, and unknown routes return `NOT_FOUND`.
- **Decided:** use the defaults, with one change. The SQLite tests override the database dependency to point at a temporary copy.
- **Why:** tests must not change the real `registry.db`.

## 3. PATCH must run the same checks as POST

- **Suggested:** the first plan did not say that PATCH re-checks the rules.
- **Decided:** PATCH merges the new fields into the existing plot, then runs the same validation on the result. A duplicate name on the same farm returns 409 `CONFLICT`. An empty farm name on PATCH returns 422 `VALIDATION`.
- **Why:** otherwise PATCH could bypass the rules that POST enforces. The spec applies the rules to plots, not to one HTTP method.

## 4. Commit locally, publish later

- **Suggested:** commit after each step.
- **Decided:** commit is done locally. Publishing (push to GitHub) waits until the user asks for it.
- **Why:** a push is visible to anyone with repo access and is hard to undo. Local commits are enough to keep history.

## 5. Which `code` to use for 405 Method Not Allowed

- **Suggested:** the task lists only four codes (`VALIDATION`, `NOT_FOUND`, `CONFLICT`, `UNAVAILABLE`), and none is an exact match for 405. Options were: one of the four, a new code, or no code.
- **Decided:** status 405 with code `VALIDATION`.
- **Why:** the status number already says exactly what happened. The code is the category, and the category is "your request is wrong, fix it". `UNAVAILABLE` would make clients retry forever. `NOT_FOUND` is misleading, because the resource exists. `CONFLICT` is about state, and no state change makes the request succeed. A new code or a missing code breaks the closed list in the task.

## 6. Split sqlite3.OperationalError by its error code

- **Suggested:** map every sqlite3.OperationalError to 503, as I first decided. Reviewing it, I found that the same error type covers both an unavailable database and a bug in a query.
- **Decided:** SQLITE_BUSY, SQLITE_LOCKED and SQLITE_CANTOPEN return 503 with Retry-After. Any other code returns 500 through the unexpected error handler.
- **Why:** a bug answered with 503 and Retry-After tells clients to keep retrying something that will never work. The error code is stable, unlike the message text, so the split is reliable.

## 7. What counts as an empty farm name

- **Suggested:** the task says a farm name must be non-empty, but does not say what "empty" means.
- **Decided:** strip spaces at the start and end of the name. A name that is empty after stripping is rejected with 422.
- **Why:** a name of only spaces cannot be read or found in a list, so it is empty in practice. Spaces at the edges are not part of the name.

## 8. What PATCH does with an empty body or a null name

- **Suggested:** the task says PATCH changes only the fields sent, but does not say what an empty body or a null name should do.
- **Decided:** an empty body returns 200 with no change. A null name returns 422.
- **Why:** "change only what was sent" means nothing changes when nothing is sent, which is harmless. A farm must always have a name, so null is invalid.

## 9. Plot names follow the farm name rule

- **Suggested:** the task requires a non-empty name for farms, but for plots it only says the name is unique inside a farm.
- **Decided:** plot names follow the farm rule. Strip the spaces around the name, and an empty result returns 422.
- **Why:** without stripping, `"North block"` and `"North block "` are different text, so a duplicate name would pass the uniqueness rule.

## 10. Unknown farm on plot create returns 404

- **Suggested:** return 422, because the bad id is inside the body, the same as `crop_id`.
- **Decided:** return 404 with code `NOT_FOUND`.
- **Why:** the task's 422 rule names only crop, soil and emitter, and its general rule says an unknown id returns 404. The detail "Farm not found" tells the client what is missing.

## 11. Duplicate plot names rely on the UNIQUE constraint

- **Suggested:** check for the name before writing, as DELETE farm did at first.
- **Decided:** rely on the UNIQUE constraint and turn `IntegrityViolation` into 409.
- **Why:** two simultaneous requests could both pass a check made before writing, and the second would get a 500.

## 12. PATCH may move a plot to another farm

- **Suggested:** the task does not say whether PATCH may change a plot's `farm_id`.
- **Decided:** allow it, so a plot can move to another farm.
- **Why:** the task says PATCH changes the fields in the body, and `farm_id` is one of them. Forbidding it would be a rule the task does not list. The existing checks already cover an unknown farm and a name taken in the new farm.

## 13. Allow the database connection to cross threads

- **Suggested:** open the connection with the sqlite3 defaults.
- **Decided:** pass `check_same_thread=False`, and keep the connection setup in one function used by the service and the tests.
- **Why:** FastAPI can run `get_db` and the route on different worker threads. With the default, overlapping requests failed with a 500. The tests missed it because they sent one request at a time. It is safe because each request has its own connection and uses it one step at a time.

## 14. Unexpected server errors return 500 with code UNAVAILABLE

- **Suggested:** the task's closed list of codes has no code for an unexpected server error.
- **Decided:** return status 500 with code `UNAVAILABLE` and no `Retry-After` header.
- **Why:** every error must be problem+json with a listed code, and a new code would break the closed list. Status 500 says what happened. Status 503 with `Retry-After` would tell clients to keep retrying a bug. This is our reading, because the task does not cover this case.

## 15. Number fields reject values that are not numbers

- **Suggested:** leave number fields with the Pydantic default, which converts `true` to 1 and `"1000"` to 1000.
- **Decided:** use `strict=True` on the number fields.
- **Why:** the task says a bad field returns 422. A client that sends `true` for an area would get 201 and a plot of 1 square metre. Whole numbers such as 1000 are still accepted.

## 16. Let the database decide overlapping writes

- **Suggested:** check first, then write. At first, DELETE farm checked for plots before deleting, because the database's foreign key error reached the client as a 500.
- **Decided:** write first, and turn the database's answer into the response: a constraint error becomes 409 or 404, and zero changed rows becomes 404.
- **Why:** another request can change the data between a check and a write. The first request to reach the database wins, and the second gets the correct error. There is no gap, and the code is shorter.

## 17. DATABASE_URL and the .env file

- **Suggested:** the agent proposed that the URL scheme picks the backend (`postgresql://` for PostgreSQL, `sqlite:///path` for SQLite), and that an unset variable means the local `registry.db`.
- **Decided:** accepted, with four additions: a relative SQLite path resolves against the service directory, an empty value counts as unset, both `postgresql://` and `postgres://` are accepted, and the password is never shown. `.env` is loaded with python-dotenv from the service directory, and a real environment variable wins over the file. The URL is parsed at app startup and stored on `app.state`. A PostgreSQL URL that libpq cannot parse also fails startup, with a fixed message that contains no part of the URL. A committed `.env.example` holds placeholders only.
- **Why:** the task requires `DATABASE_URL` explicitly. An unset variable means SQLite, so local runs and the default tests need no configuration. Parsing at startup makes a bad URL visible at deploy, and `app.state` (not a module-level cache) keeps one test from inheriting another test's database.

## 18. A thin adapter over raw SQL, not an ORM

- **Suggested:** the agent compared three approaches: a thin adapter with raw SQL, SQLAlchemy Core, and separate code for each database.
- **Decided:** the thin adapter. Routers keep their SQL with `?` placeholders, and the only new database dependency is `psycopg`.
- **Why:** identical behavior is easiest to keep when one place translates errors and placeholders. SQLAlchemy Core means rewriting all the SQL and a heavier dependency. Separate code per database doubles the code and the risk of drift.

## 19. Reject a literal % in SQL, on both backends

- **Suggested:** the agent's adapter translated `?` to `%s` for PostgreSQL and did not mention `%`.
- **Decided:** `execute` raises a clear programming error when the SQL contains `%`, on both backends.
- **Why:** psycopg treats `%` as special, so a literal one would break later in a confusing way. Checking on SQLite too means the default test run catches the mistake before production does.

## 20. PostgreSQL column types mirror SQLite

- **Suggested:** the agent offered three options: mirror SQLite, use native types (`DATE`, `NUMERIC`, `UUID`), or use `DATE` for `planting_date` only.
- **Decided:** mirror SQLite: `TEXT`, `INTEGER`, `DOUBLE PRECISION`. Native types are a non-goal.
- **Why:** psycopg then returns `str`, `int` and `float`, as sqlite3 does, so no conversion code is needed and behavior cannot drift. Validation already happens in Pydantic. Native types can be a separate, later task.

## 21. COLLATE "C" on every TEXT column

- **Suggested:** the type mapping in entry 20 said nothing about sort order. Review found that PostgreSQL uses the database's locale collation by default, which can order ids differently from SQLite's byte order.
- **Decided:** every `TEXT` column in the PostgreSQL schema is `COLLATE "C"`. A test checks list order on both backends, with ids that differ under locale ordering (mixed case and punctuation).
- **Why:** every list endpoint uses `ORDER BY id`, so a different order would be a visible behavior difference.

## 22. The PostgreSQL schema is a script run by hand, never on startup

- **Suggested:** the open question was whether the schema already exists in production or the service must create it.
- **Decided:** the tables do not exist. The service ships a schema script, run by hand as one transaction, that creates the tables and loads only the catalogues (crops, soils, emitters). Demo farms and plots are in a separate file for local use and tests. The script has no `IF NOT EXISTS` and no schema name. A test compares the SQLite seed and the PostgreSQL scripts, table by table.
- **Why:** a production schema change should be deliberate, and creating tables at startup would hide failures and need write rights at runtime. Demo data must never reach production. A second run should fail loudly. With no schema name, the test fixture can run the same script in its own schema. The comparison test stops the two copies of the catalogues from drifting apart.

## 23. One connection per request; a pool is deferred

- **Suggested:** the agent offered a connection per request, a pool for PostgreSQL only, or a pool for both.
- **Decided:** one connection per request, opened and closed in `get_db`, on both backends. A pool can be added behind `get_db` if `scripts/measure_p95.py` shows a real problem.
- **Why:** it is the smallest change and keeps the structure as it is. A pool adds a dependency, sizing, a lifecycle and a second code path, and nothing shows yet that it is needed.

## 24. Connect and lock timeouts on PostgreSQL

- **Suggested:** the agent's per-request connection used PostgreSQL's defaults.
- **Decided:** `connect_timeout` of 5 seconds, and `lock_timeout` of 5 seconds on every connection, appended to any `options` already in the URL and never replacing them.
- **Why:** without a connect timeout an unreachable server can hang for about two minutes instead of returning 503 quickly. SQLite waits 5 seconds for a lock and then returns `SQLITE_BUSY`, which becomes 503, but PostgreSQL waits forever by default, so a locked row would never give 503.

## 25. Which PostgreSQL errors return 503, after the connection is open

- **Suggested:** the agent proposed the same split as entry 6, by SQLSTATE: `08*`, `57P01`, `57P02`, `57P03`, `53300`, `55P03`, `40001` and `40P01` return 503 with `Retry-After`, and everything else returns 500.
- **Decided:** accepted, plus one rule: an `OperationalError` outside that list returns 503 when `conn.broken` is true.
- **Why:** only cases where a retry can help should return 503, as in entry 6. A dropped connection can arrive without a SQLSTATE. Checked against PostgreSQL 17: a stopped server, a killed server, a terminated backend and a cut socket all leave `conn.broken` true, while ordinary errors (`42P01`, `23505`) leave it false.

## 26. Every failure while opening the connection returns 503

- **Suggested:** the agent proposed that wrong password (`28*`) and missing database (`3D000`) return 500, with the argument of entry 6, because a retry cannot fix them.
- **Decided:** reversed for connect time. Any failure while opening the connection returns 503 with `Retry-After`: wrong password, unknown user, missing database, unreachable server, server starting up. There is no `pgconn` heuristic and no TCP probe.
- **Why:** checked against PostgreSQL 17 with psycopg 3.3.8: all four connect failures raise `OperationalError` with `sqlstate=None`, so any split would rely on fragile internals. It also matches SQLite, where a missing file (`SQLITE_CANTOPEN`) returns 503. That is a pre-existing SQLite choice and is not being changed. The cost is that a misconfiguration looks like an outage to clients, so the real cause must be in the server log (entry 27).

## 27. Log only on the 503 path, and never log secrets

- **Suggested:** the agent noted that the 503 handler wrote no log line, so the real cause of a database outage would be invisible.
- **Decided:** the adapter logs only when it raises `DatabaseUnavailable`: the exception class, the SQLite error name or PostgreSQL SQLSTATE when there is one, and the exception text only for `psycopg.OperationalError` and SQLite errors. Any other exception raised while building the connection settings or opening the connection is logged by class name and a fixed message only. It never logs `e.pgconn`, the URL or the parameters. Integrity violations and the NUL guards write no log line.
- **Why:** the log is where whoever runs the service finds a misconfiguration (entry 26). `e.pgconn` contains the password in clear text, and libpq messages include host and user. A 409 for a duplicate name is a normal client answer and should not write a warning each time. A malformed percent escape in the password made psycopg's URL parser put the password into its error text, so the text is withheld for every class except those known to carry only host, port, user and the server's own message.

## 28. Roll back before raising IntegrityViolation

- **Suggested:** review found that after an `IntegrityError`, `plots.py` (create and update) runs `check_references` again on the same connection.
- **Decided:** the adapter rolls back as soon as it catches an integrity violation, before it raises `IntegrityViolation`. A test covers create and update, on both backends. If the rollback fails because the connection is gone, the adapter raises `DatabaseUnavailable`.
- **Why:** on PostgreSQL an aborted transaction fails every later query, which would turn a 409 or 404 into a 500. The rollback is harmless on SQLite, so there is one code path.

## 29. NUL in request body text returns 422, on both backends

- **Suggested:** the open question was that PostgreSQL rejects `\u0000` in text while SQLite accepts it, so a farm name with NUL returns 201 today and would fail on PostgreSQL.
- **Decided:** NUL in any text field of a request body (the names and `farm_id`, `crop_id`, `soil_id`, `emitter_id`) returns 422 `VALIDATION`, "Text contains invalid characters", on both backends. On SQLite this changes 201 to 422.
- **Why:** it is the only option that gives identical behavior on both backends. A NUL in a name is corrupt data, and nothing existing tests or documents it. The change is deliberate and recorded here on purpose.

## 30. NUL in a path or query id keeps today's answer, without querying

- **Suggested:** a NUL in a lookup value is also sent to the database as a parameter. On SQLite today it gives 404 (or `200 []` for the `farm_id` filter), and on PostgreSQL psycopg would raise `DataError` and the request would become a 500.
- **Decided:** each of the 10 id-taking sites returns today's SQLite answer before any query, through an explicit `contains_nul` check. A route-walking test over `app.openapi()["paths"]` asserts exactly 10 sites, and a spy on the adapter asserts that no query received a NUL parameter. The guard counts as part of the identical-behavior requirement.
- **Why:** a value with NUL can never match a stored id. An explicit guard keeps the behavior visible in each route, unlike a guard in the adapter, which would also silence real stores. The test uses the OpenAPI schema because `app.routes` does not list included routers in this FastAPI version, and it asserts the count, so it can never pass on an empty list.

## 31. The default test run stays on SQLite, and entry 2's override stays

- **Suggested:** the agent first described fixtures that set `DATABASE_URL`, which differed from entry 2's mechanism.
- **Decided:** SQLite fixtures keep overriding `get_db` with a temp copy of `registry.db`. One autouse fixture sets `DATABASE_URL` to a SQLite URL so startup never reads the developer's `.env`. Tests use PostgreSQL only through `TEST_DATABASE_URL`, never through `DATABASE_URL`. Tests prove that a PostgreSQL URL in the environment, and a bad or PostgreSQL URL in `.env`, do not change the default run.
- **Why:** the requirement is that the default run uses SQLite only, and a developer's `.env` may hold a PostgreSQL URL. A real environment variable beats `.env`, so the app needs no test-only branch.

## 32. PostgreSQL test isolation, and the same-database safety check

- **Suggested:** the agent offered a fresh schema per test, truncating and reseeding the same tables, or a new database per test.
- **Decided:** one schema per test, named with a fixed `test_` prefix. The fixture runs the schema script and the demo data inside it, puts `options=-csearch_path=<schema>` in the URL it gives the app, and drops only the schema it created, by exact name. The tests run only when `TEST_DATABASE_URL` is set, and refuse to run when it points at the same database as the developer's real `DATABASE_URL`. That value is captured once at session start, before any fixture changes it, and compared by host, port and database name. A `TEST_DATABASE_URL` that is not a `postgresql://` or `postgres://` URL with a host (a key=value string, a socket-style URL) is refused too, because the comparison cannot read it.
- **Why:** a schema per test is isolated, can run in parallel, needs no extra privileges and exercises the schema script itself. The safety check keeps the tests away from a production database. Capturing the URL early matters, because the autouse fixture overwrites the variable, and a later comparison would always be against SQLite.

## 33. The parallel tests run on both backends

- **Suggested:** the open question was whether `tests/test_parallel.py` should run on PostgreSQL.
- **Decided:** all four tests run on both backends, with the assertions unchanged. A 503 or 500 there is a finding to investigate, not a reason to widen the allowed set.
- **Why:** real concurrency and row locks are where PostgreSQL differs most from SQLite, and the farm-delete race exercises the rollback-then-`check_references` path (entry 28).
