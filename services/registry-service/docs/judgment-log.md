# Judgment log

Each entry: what the AI tools suggested or the open question they raised, what I decided, and why.

## 1. Where to turn database failures into HTTP 503

- **Suggested:** the agent first planned to put the 503 mapping in `db.py`.
- **Decided:** `db.py` classifies the errors the database driver raises (SQLAlchemy wraps them, and `classify_error` reads the driver error under the wrapper) and raises its own `DatabaseUnavailable`. `errors.py` has the exception handler that turns it into 503. `db.py` knows nothing about HTTP.
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
- **Decided:** SQLITE_BUSY, SQLITE_LOCKED and SQLITE_CANTOPEN return 503 with Retry-After. Any other code returns 500 through the unexpected error handler. The code is read from the driver error under SQLAlchemy's wrapper (`sqlite_errorname`).
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
- **Decided:** rely on the UNIQUE constraint and turn `IntegrityViolation` into 409. `db.py` raises `IntegrityViolation` for SQLAlchemy's `IntegrityError`, whichever driver is under it.
- **Why:** two simultaneous requests could both pass a check made before writing, and the second would get a 500.

## 12. PATCH may move a plot to another farm

- **Suggested:** the task does not say whether PATCH may change a plot's `farm_id`.
- **Decided:** allow it, so a plot can move to another farm.
- **Why:** the task says PATCH changes the fields in the body, and `farm_id` is one of them. Forbidding it would be a rule the task does not list. The existing checks already cover an unknown farm and a name taken in the new farm.

## 13. Allow the database connection to cross threads

- **Suggested:** open the connection with the sqlite3 defaults.
- **Decided:** pass `check_same_thread=False` when the SQLite engine is built, and keep the connection setup in one place used by the service and the tests (`create_engine_for` and `open_connection` in `db.py`).
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
- **Decided:** accepted, with four additions: a relative SQLite path resolves against the service directory, an empty value counts as unset, both `postgresql://` and `postgres://` are accepted, and the password is never shown. `.env` is read with pydantic-settings (the `Settings` class in `config.py`) from the service directory, not the working directory, and a real environment variable wins over the file, even an empty one. The URL is parsed at app startup and stored on `app.state`. libpq's own parse is the authority for a PostgreSQL URL: at startup it is cross-checked against a plain URL split, and a URL that libpq cannot parse, that the two read differently (for example an unencoded `@` in the password), that has an unencoded `@` after the authority, or whose port is not a number from 1 to 65535 fails startup with a fixed message that contains no part of the URL. A committed `.env.example` holds placeholders only.
- **Why:** the task requires `DATABASE_URL` explicitly. An unset variable means SQLite, so local runs and the default tests need no configuration. Parsing at startup makes a bad URL visible at deploy, and `app.state` (not a module-level cache) keeps one test from inheriting another test's database.

## 18. SQLAlchemy Core with the SQL kept as text, behind the existing wrapper

- **Suggested:** the agent compared three approaches: a thin adapter with raw SQL, SQLAlchemy Core, and separate code for each database. For the PostgreSQL work it recommended the thin adapter.
- **Decided:** reversed for P2, which requires all data access to go through SQLAlchemy. The SQL stays as text (`sqlalchemy.text`), with no ORM and no query builder. The `Connection` and `Result` wrapper in `db.py` stays and runs on a SQLAlchemy engine. Routers change only their placeholders (`:name`) and pass a dict. Of the three ways to do it, keeping the wrapper beat dropping it (every router would change) and beat keeping `?` with a hidden conversion inside the wrapper.
- **Why:** identical behavior is easiest to keep when one place translates errors (entry 1). Keeping the wrapper leaves the routers' logic and the 503 rules where they were, so the change is mostly mechanical. Separate code per database still doubles the code and the risk of drift.

## 19. A literal % in SQL is safe; a literal : must be escaped

- **Suggested:** the old adapter rejected any SQL that contained `%`, because psycopg treats `%` as special. The move to SQLAlchemy raised the question whether that guard is still needed.
- **Decided:** the guard is gone. Checked on 2026-11-15 with SQLAlchemy 2.1.8: `text()` doubles a literal `%` for psycopg and leaves it alone for SQLite. A literal `:` in SQL text is read as a parameter and must be written `\:`. The routers' SQL has none. Tests run a query with a literal `%` and a bound value that holds `:` and `%` (a farm named `50% :off`) on both backends.
- **Why:** a rule that protects against nothing is noise, and a test that proves the opposite (a `%` query works on both backends) is better than a guard. The new hazard is the colon, and it is documented here and covered by the same tests.

## 20. PostgreSQL column types mirror SQLite

- **Suggested:** the agent offered three options: mirror SQLite, use native types (`DATE`, `NUMERIC`, `UUID`), or use `DATE` for `planting_date` only.
- **Decided:** mirror SQLite: `TEXT`, `INTEGER`, `DOUBLE PRECISION`. Native types are a non-goal.
- **Why:** psycopg then returns `str`, `int` and `float`, as sqlite3 does, so no conversion code is needed and behavior cannot drift. Validation already happens in Pydantic. Native types can be a separate, later task.

## 21. COLLATE "C" on every TEXT column

- **Suggested:** the type mapping in entry 20 said nothing about sort order. Review found that PostgreSQL uses the database's locale collation by default, which can order ids differently from SQLite's byte order.
- **Decided:** every `TEXT` column in the PostgreSQL schema is `COLLATE "C"`. A test checks list order on both backends, with ids that differ under locale ordering (mixed case and punctuation).
- **Why:** every list endpoint uses `ORDER BY id`, so a different order would be a visible behavior difference.

## 22. The PostgreSQL tables come from a seed command run by hand, never on startup

- **Suggested:** the open question was whether the schema already exists in production or the service must create it.
- **Decided:** the tables do not exist. The service ships one command, `uv run python scripts/seed.py` (entries 43 to 45), that creates the five tables from `sql/postgres_schema.sql` and loads all 15 sample rows from `sql/seed_data.sql`, in one transaction, with no flag. The schema file has no `IF NOT EXISTS` and no schema name. The service never creates tables. A test compares the PostgreSQL rows with the SQLite seed, table by table.
- **Why:** a production schema change should be deliberate, and creating tables at startup would hide failures and need write rights at runtime. P2 asks for one documented command that creates the tables and loads the same 15 rows as `seed_registry.sh`, so the command loads them all and the README says it loads sample data. A second run should fail loudly. With no schema name, the test fixture can run the same code in its own schema. The comparison test stops the two seeds from drifting apart.

## 23. One connection per request; a pool is deferred

- **Suggested:** the agent offered a connection per request, a pool for PostgreSQL only, or a pool for both.
- **Decided:** one connection per request, opened and closed in `get_db`, on both backends (a `NullPool` engine, entry 35). A pool can be added behind `get_db` if `scripts/measure_p95.py` shows a real problem. It showed none (entry 47).
- **Why:** it is the smallest change and keeps the structure as it is. A pool adds a dependency, sizing, a lifecycle and a second code path, and nothing shows yet that it is needed.

## 24. Connect and lock timeouts on PostgreSQL

- **Suggested:** the agent's per-request connection used PostgreSQL's defaults.
- **Decided:** `connect_timeout` of 5 seconds, and `lock_timeout` of 5 seconds on every connection, appended to any `options` already in the URL and never replacing them. `postgres_connect_args` in `config.py` builds them, and the engine passes them to the driver as connect arguments.
- **Why:** without a connect timeout an unreachable server can hang for about two minutes instead of returning 503 quickly. SQLite waits 5 seconds for a lock and then returns `SQLITE_BUSY`, which becomes 503, but PostgreSQL waits forever by default, so a locked row would never give 503.

## 25. Which PostgreSQL errors return 503, after the connection is open

- **Suggested:** the agent proposed the same split as entry 6, by SQLSTATE: `08*`, `57P01`, `57P02`, `57P03`, `53300`, `55P03`, `40001` and `40P01` return 503 with `Retry-After`, and everything else returns 500.
- **Decided:** accepted, plus one rule: an `OperationalError` outside that list returns 503 when SQLAlchemy reports the connection as invalidated (`connection_invalidated` on its exception).
- **Why:** only cases where a retry can help should return 503, as in entry 6. A dropped connection can arrive without a SQLSTATE. Checked against PostgreSQL 17 with psycopg directly: a stopped server, a killed server, a terminated backend and a cut socket all leave `conn.broken` true, while ordinary errors (`42P01`, `23505`) leave it false. Under SQLAlchemy the same signal arrives as the invalidated flag, and the cut-socket and terminated-backend tests in `tests/test_postgres_failures.py` confirm the 503 end to end.

## 26. Every failure while opening the connection returns 503

- **Suggested:** the agent proposed that wrong password (`28*`) and missing database (`3D000`) return 500, with the argument of entry 6, because a retry cannot fix them.
- **Decided:** reversed for connect time. Any failure while opening the connection returns 503 with `Retry-After`: wrong password, unknown user, missing database, unreachable server, server starting up. There is no `pgconn` heuristic and no TCP probe.
- **Why:** checked against PostgreSQL 17 with psycopg 3.3.8: all four connect failures raise `OperationalError` with `sqlstate=None`, so any split would rely on fragile internals. It also matches SQLite, where a missing file (`SQLITE_CANTOPEN`) returns 503. That is a pre-existing SQLite choice and is not being changed. The cost is that a misconfiguration looks like an outage to clients, so the real cause must be in the server log (entry 27).

## 27. Log only on the 503 path, and never log secrets

- **Suggested:** the agent noted that the 503 handler wrote no log line, so the real cause of a database outage would be invisible.
- **Decided:** the adapter logs only when it raises `DatabaseUnavailable`: the exception class, the SQLite error name or PostgreSQL SQLSTATE when there is one, and the exception text only for `psycopg.OperationalError` and SQLite errors. It formats the driver error under SQLAlchemy's wrapper, never the wrapper's own text, which holds the SQL (entries 40 and 41). Any other exception raised while opening the connection is logged by class name and a fixed message only. It never logs `e.pgconn`, the URL or the parameters. Integrity violations and the NUL guards write no log line.
- **Why:** the log is where whoever runs the service finds a misconfiguration (entry 26). `e.pgconn` contains the password in clear text, and libpq messages include host and user. A 409 for a duplicate name is a normal client answer and should not write a warning each time. A malformed percent escape in the password made psycopg's URL parser put the password into its error text, so the text is withheld for every class except those known to carry only host, port, user and the server's own message. The startup check (entry 17) keeps URLs that libpq and a plain URL split read differently out of the log path, because libpq's error text repeats whatever it took for the host, the port or the database name.

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
- **Decided:** each of the 10 id-taking sites returns today's SQLite answer before any query, through an explicit `contains_nul` check. A route-walking test over `app.openapi()["paths"]` asserts exactly 10 sites, and a spy on the adapter asserts that no query received a NUL parameter. Parameters are dicts now, so the spy reads their values, and a control request proves the spy sees named parameters. The guard counts as part of the identical-behavior requirement.
- **Why:** a value with NUL can never match a stored id. An explicit guard keeps the behavior visible in each route, unlike a guard in the adapter, which would also silence real stores. The test uses the OpenAPI schema because `app.routes` does not list included routers in this FastAPI version, and it asserts the count, so it can never pass on an empty list.

## 31. The default test run stays on SQLite, and entry 2's override stays

- **Suggested:** the agent first described fixtures that set `DATABASE_URL`, which differed from entry 2's mechanism.
- **Decided:** SQLite fixtures keep overriding `get_db` with a temp copy of `registry.db`. One autouse fixture sets `DATABASE_URL` to a SQLite URL so startup never reads the developer's `.env`. Tests use PostgreSQL only through `TEST_DATABASE_URL`, never through `DATABASE_URL`. Tests prove that a PostgreSQL URL in the environment, and a bad or PostgreSQL URL in `.env`, do not change the default run.
- **Why:** the requirement is that the default run uses SQLite only, and a developer's `.env` may hold a PostgreSQL URL. A real environment variable beats `.env`, so the app needs no test-only branch.

## 32. PostgreSQL test isolation, and the same-database safety check

- **Suggested:** the agent offered a fresh schema per test, truncating and reseeding the same tables, or a new database per test.
- **Decided:** one schema per test, named with a fixed `test_` prefix. The fixture creates the tables and loads the 15 rows inside it with the same `seed_postgres` function as the seed command (a separate `empty_pg_schema` fixture gives the seed tests an empty schema), puts `options=-csearch_path=<schema>` in the URL it gives the app, and drops only the schema it created, by exact name. The tests run only when `TEST_DATABASE_URL` is set, and refuse to run when it points at the same database as the developer's real `DATABASE_URL`, captured once at session start before any fixture changes it, from the environment and `.env`, as the service reads them (entry 39). The comparison uses libpq's parse: host (`localhost`, `127.0.0.1` and `::1` count as one host), port, and database name, which defaults to the user name; an unknown database name matches any database on the same host and port. A `TEST_DATABASE_URL` that is not a `postgresql://` or `postgres://` URL with a host, or that holds `service`, `hostaddr`, a host list or a port that is not plain digits from 1 to 65535, is refused too, because the comparison cannot read it. Different names for the same server (for example `localhost.` or `127.1`) are not detected.
- **Why:** a schema per test is isolated, can run in parallel, needs only the right to create schemas and exercises the seed command's own code. The safety check keeps the tests away from a production database. Capturing the URL early matters, because the autouse fixture overwrites the variable, and a later comparison would always be against SQLite.

## 33. The parallel tests run on both backends

- **Suggested:** the open question was whether `tests/test_parallel.py` should run on PostgreSQL.
- **Decided:** all four tests run on both backends, with the assertions unchanged. A 503 or 500 there is a finding to investigate, not a reason to widen the allowed set.
- **Why:** real concurrency and row locks are where PostgreSQL differs most from SQLite, and the farm-delete race exercises the rollback-then-`check_references` path (entry 28).

## 34. Farm and plot names are limited to 200 characters

- **Suggested:** the final review found that PostgreSQL limits an index row to about 2704 bytes and the plot name is part of `UNIQUE (farm_id, name)`, so an incompressible name of a few thousand characters fails with SQLSTATE 54000 (a 500) while SQLite accepts it. The options were a maximum length on both backends or accepting and recording the difference.
- **Decided:** farm and plot names are limited to 200 characters, counted after the surrounding spaces are stripped, on both backends. A longer name returns 422 `VALIDATION`. This changes SQLite behavior: a longer name used to return 201.
- **Why:** identical behavior on both backends needs one rule. 200 characters stay far below the index limit even for four-byte characters (800 bytes plus the farm id) and are enough for a farm or plot name. Checked on PostgreSQL 17: a 4160-character incompressible value in the unique index failed, a 1500-character one did not.

## 35. NullPool on both engines instead of SQLAlchemy's default pool

- **Suggested:** found while planning P2: SQLAlchemy pools connections by default, for PostgreSQL and for a SQLite file. That would have quietly replaced entry 23 (one connection per request) and made the rule "add a pool only if p95 is over 100 ms" meaningless, because a pool would already be there.
- **Decided:** `NullPool` on both backends. Every request opens its own connection in `get_db` and closes it in the `finally`, as before. A test checks that both engines use `NullPool`. With no pool, nothing but `get_db`'s `finally` ends a connection, so a test drives `get_db` as a generator with a stub connection and checks that `close()` ran, also when the route raises. Without that close, a PostgreSQL backend stays open and idle in a transaction, and the suite can hang on its locks.
- **Why:** the behavior stays what entry 23 describes, so the measurement in entry 47 says something about a pool-less service, and adding a pool stays a separate, logged decision.

## 36. The PostgreSQL engine uses the psycopg driver and libpq connect arguments

- **Suggested:** SQLAlchemy picks `psycopg2` for a bare `postgresql://` URL, and `psycopg2` is not a dependency of this service.
- **Decided:** the engine is created with the URL `postgresql+psycopg://` and nothing else. Host, user, password, port, database and the timeouts of entry 24 go in as libpq parameters (`connect_args`, from `postgres_connect_args`). `DATABASE_URL` keeps accepting `postgresql://` and `postgres://`. If the URL cannot be read by libpq, `create_engine_for` raises a `ConfigError` with a fixed message and drops the driver's error, which can hold the password. Startup validation already rejects such a URL first, so this is a second line of defence.
- **Why:** libpq stays the authority for what a URL means (entry 17), the `options` merge and timeouts keep working, and the password never sits in a SQLAlchemy URL object that could be printed.

## 37. Settings errors never echo the input

- **Suggested:** pydantic's own validation error text can repeat the value it rejected, which here could be a URL with a password.
- **Decided:** `Settings` in `config.py` uses `pydantic-settings` with `extra="ignore"`, so other keys in `.env` (such as `TEST_DATABASE_URL`) are ignored. The `DATABASE_URL` field has `repr=False`, so `repr` and `str` of the settings never show the URL. Every bad `DATABASE_URL` is rejected by the existing check, which raises `ConfigError`. That is not a `ValueError`, so pydantic lets it through unchanged, and every `ConfigError` in `config.py` is raised outside its `except` block (entry 41). `hide_input_in_errors` and the branch in `load_settings` that turns a pydantic `ValidationError` into `ConfigError("Invalid settings")` are a backstop only: no input reaches them today, because every bad URL fails in the check first, and no test exercises them. The `.env` file is found next to `config.py`, not in the working directory, and a real environment variable wins over it, even an empty one (which means SQLite).
- **Why:** the fixed messages of entry 17 must survive the change of library. Tests check that an invalid URL stops startup, that the message, the traceback and the exception chain do not hold the URL, that `repr` and `str` do not show it, and the precedence rules. They cover these active protections. The backstop is not tested.

## 38. DATABASE_URL stays optional, and the README says how the "missing required variable" rule is met

- **Suggested:** P2 says a missing required variable stops startup with a clear error, but `DATABASE_URL` is optional (unset means local SQLite), so nothing in the registry is required. Three options: keep it optional, require it in production only (which needs a new variable such as `APP_ENV`), or require it everywhere (which undoes the SQLite default).
- **Decided:** keep it optional. The README states that the "missing required variable" rule is demonstrated in the new services, and that the registry fails loudly on an invalid value instead.
- **Why:** an optional URL is what makes local runs and the default tests need no configuration (entry 17). The other two options add a variable nobody asked for or take that convenience away. The cost is that this one requirement is met in spirit here, and the README says so.

## 39. A test-only settings class reads TEST_DATABASE_URL and the developer's DATABASE_URL

- **Suggested:** the old code copied `.env` into the process environment at import, which is how the tests found `TEST_DATABASE_URL` and the developer's `DATABASE_URL`. `pydantic-settings` does not do that, so a URL kept only in `.env` would silently vanish from the same-database safety check of entry 32.
- **Decided:** `TestEnv` in `tests/pg_support.py` reads both values raw, from the environment and then `.env`, with no validation, so a bad URL cannot stop the test session. `__test__ = False` keeps pytest from collecting it. Tests check that URLs kept only in `.env`, with no real variable set, reach `TestEnv` and make the safety check refuse. The check was shown to fail when `TestEnv` was pointed at the wrong file.
- **Why:** the safety check exists to keep the tests away from a real database. A check that cannot see where the developer's URL lives protects nothing.

## 40. hide_parameters on both engines, as a second line of defence

- **Suggested:** SQLAlchemy's own error text holds the SQL and, unless told otherwise, the bound parameters, such as a farm name.
- **Decided:** `hide_parameters=True` on both engines, in addition to the rule of entry 27 that only the driver error is ever logged. A test per backend runs a failing statement with a marker parameter on a real engine and checks that the error text has the SQL but not the marker.
- **Why:** the independent review of the data-access change found that removing the setting left the whole suite green. The setting is cheap, and with a test behind it nobody can drop it unnoticed. Removing it on purpose now fails those tests.

## 41. Translated errors are raised after the except block ends

- **Suggested:** the first version raised its translated errors inside the `except` block with `from None`. The review showed that `from None` only hides the old exception from printouts. Python stores it in `__context__` at the moment of the raise, so SQLAlchemy's exception, whose text holds the SQL, stayed reachable for any tool that walks the chain. Clearing `__context__` before the raise would not have held, because Python sets it again when the raise happens.
- **Decided:** `Connection._translated` returns the error to raise and never raises it. `execute`, `commit`, the two fetch methods, `open_connection` and the engine factory raise it after their `except` block ends. The raised `DatabaseUnavailable`, `IntegrityViolation` and `ConfigError` therefore have no `__context__`, and the original driver error is re-raised unchanged for the 500 path. Tests check the chain on every entry point, with the failed-rollback case, and on a real 500 path on both backends: no SQLAlchemy exception in the chain and no marker in the traceback. Removing the change at any one entry point turns its test red. The same rule holds for the `ConfigError`s in `config.py`: the final review found that the URL-parse error was raised inside its handler, so the parser's message, which can hold the netloc and so the password, stayed in `__context__`. It now follows the pattern, and a test per place that raises checks the chain. The older `from None` stays, because an existing test requires the context to be marked as suppressed.
- **Why:** a secret that sits in a hidden attribute is still a leak for error reporters and debuggers. Raising outside the handler fixes the cause, not the printout.

## 42. IntegrityViolation carries a fixed message

- **Suggested:** the exception used the driver's message, and PostgreSQL's text for a unique violation includes `DETAIL: Key (id)=(...)`, which holds key values.
- **Decided:** the message is always `Integrity constraint violated`. Routers never read it. Tests check it for a PostgreSQL-style error with a marker key and for a real SQLite error.
- **Why:** it was never logged, but an exception that holds data can end up in a log or an error report later. A fixed text costs nothing and removes the question.

## 43. One shared seed_data.sql feeds both backends

- **Suggested:** the 15 sample rows lived in three places (`seed_registry.sh`, the catalogues in `postgres_schema.sql`, and `demo_data.sql`), kept equal only by a comparison test.
- **Decided:** `sql/seed_data.sql` holds the 15 rows once, in foreign-key order. `seed_registry.sh` keeps its own SQLite table definitions and loads the rows from that file, through the script's own directory, so it works from any working directory (`sqlite3 -bail` stops on a bad row). `postgres_schema.sql` holds tables only, and `demo_data.sql` is gone. A test rebuilds the SQLite file from another working directory and compares its rows and schema with hashes captured before the change (rows `5fca1040563d1f47fddc664b110a6ab3ff893164c61720bd8e7bd46b046f3797`, schema `b1029b6385bfd75548d44a337323d8e849b6fa50887622e9894a9c831f77c809`). The drift test between PostgreSQL and SQLite stays.
- **Why:** with one source the two seeds cannot disagree, and the hashes prove that moving the rows changed nothing. Table definitions stay per backend because `COLLATE "C"` and `DOUBLE PRECISION` cannot be shared. Each guard was shown to fail by changing a value, an insert order, a table definition and the file path on purpose.

## 44. seed.py loads PostgreSQL only, and its messages show nothing from the exception

- **Suggested:** the command could also seed SQLite, but `seed_registry.sh` already does.
- **Decided:** `scripts/seed.py` reads `DATABASE_URL` through `config.py` and refuses a SQLite target, including an unset or empty variable (which means SQLite), with a message pointing at `seed_registry.sh`. It creates nothing in that case. Every failure after the target is accepted prints one fixed sentence: the tables already exist, the database is unavailable or refused the connection, or seeding failed, each followed by "Nothing was changed". Tests run the real command as a subprocess and check the exit code, the text, that there is no traceback, and that the output holds no password, host or URL.
- **Why:** a seed command that can also hit a SQLite file invites running it against the wrong database. The driver's error text can hold the host and the user (entry 27), so none of it is printed.

## 45. The seed runs in one transaction, and a test proves it

- **Suggested:** a second run already fails on its first statement, because the first table exists, so that case alone cannot show whether the seed is atomic.
- **Decided:** `seed_postgres` runs the schema and the rows in one transaction, so any failure rolls everything back. A test makes only `plots` exist beforehand, so the seed creates four tables and then fails on `plots`, and asserts that the other four tables are gone. Other tests check that a second run fails and changes no row, and that empty existing tables stay empty. Running each statement in its own commit turns the atomicity test red, and swallowing errors turns four tests red.
- **Why:** half a seed is worse than none. Without this test a regression to per-statement commits would pass every other test.

## 46. Rows are plain dicts, and the row count is read before the commit

- **Suggested:** `sqlite3.Row` allowed access by position and by name, psycopg's `dict_row` by name only, and SQLAlchemy returns its own row objects. Also, the cursor closes once a statement is done, and the routers read `rowcount` after the commit.
- **Decided:** `Result.fetchone` and `fetchall` return plain dicts, and `Result` reads `rowcount` when the statement runs. Tests that read a row by position now read it by column name.
- **Why:** the routers only ever used names, and dicts behave the same on both backends. Reading `rowcount` early is a precaution: the cursor closes once the statement is done, and the routers read the count after the commit. With SQLAlchemy 2.1.8 the count survives the close anyway, so `test_rowcount_survives_the_commit` proves the answer is right after a commit, but it cannot detect a regression to a late read.

## 47. PostgreSQL p95 is 34.2 ms, so no pool was added

- **Suggested:** entry 23 said to add a pool only if `scripts/measure_p95.py` shows a real problem, and the 8.8 ms in the old README was measured on SQLite only.
- **Decided:** measured on PostgreSQL 17.11 in a local container (WSL2, reached through Docker, one uvicorn process, no pool), seeded with `scripts/seed.py`: 1200 requests at 10 per second over 120 seconds, no response other than 200, overall p95 34.2 ms, per route from 29.0 ms to 40.0 ms. No pool was added. The SQLite figure of 8.8 ms (task P1) was not repeated and stays labeled as SQLite. The README says the PostgreSQL figure is probably higher because each request opens a new connection. That was not measured separately.
- **Why:** 34.2 ms is well under the 100 ms target (NFR-2.2), and a pool adds sizing, a lifecycle and a second code path (entry 23). Naming a cause that was not measured as a fact would be a guess in a document people trust, so the README says "probably".
