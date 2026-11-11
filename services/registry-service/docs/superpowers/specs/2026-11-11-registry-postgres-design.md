# Registry service on SQLite and PostgreSQL: design

Status: draft for review. Branch: `p1-postgres`. Date: 2026-11-11.

## 1. Goal and success criteria

`registry-service` runs on SQLite (local use and tests) and on PostgreSQL (production). The backend is chosen by `DATABASE_URL`. The endpoints behave exactly the same on both: status codes, problem+json codes, and `Retry-After` on 503.

Success means all of these:

1. Every existing test passes on SQLite with no behavior change, except the one deliberate change in section 8 (NUL in text).
2. With a real PostgreSQL, the same tests pass there too (section 10).
3. The default test run uses SQLite only, whatever `DATABASE_URL` says.
4. `DATABASE_URL` is chosen by the scheme, and secrets never appear in logs or error messages.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Both backends | SQLite and PostgreSQL, not a replacement. |
| Production PostgreSQL | The server and database exist and `DATABASE_URL` is given. The tables do not. |
| Schema | A script that is run by hand, never on app startup. In production it creates the tables and loads only the catalogues (crops, soils, emitters). Demo farms and plots are local and test only. |
| Data access | A thin adapter over raw SQL, no ORM. |
| Connection lifetime | One connection per request, opened and closed in `get_db`, on both backends. A pool is deferred (section 12). |
| Column types | Mirror SQLite: `TEXT`, `INTEGER`, `DOUBLE PRECISION`. Native types (`DATE`, `NUMERIC`, `UUID`) are a non-goal. |
| Collation | Every `TEXT` column is `COLLATE "C"`, so `ORDER BY id` is byte order, as in SQLite. |
| Dependencies | `psycopg[binary]~=3.3` (tested with 3.3.8) and `python-dotenv`. Added only after this spec is approved. |

## 3. Configuration

New `config.py`.

- **Loading.** It loads `.env` from the service directory with `override=False`, so a real environment variable wins over the file. Loading `.env` only fills environment variables; nothing is parsed at import.
- **Parsing.** `DATABASE_URL` is parsed into a target: SQLite (a path) or PostgreSQL (a connection string).
  - `postgresql://` and `postgres://` select PostgreSQL.
  - `sqlite:///path` selects SQLite. A relative path resolves against the service directory, like `DB_PATH` today, not against the working directory.
  - Unset or empty means the local `registry.db`.
  - Any other scheme is an error.
- **Secrets.** The target object redacts the password in its `repr`. Nothing formats the full URL. Error messages and logs never include it.
- **When it is parsed.** At app startup, in a lifespan handler. Never at import and never on the first request. A bad scheme fails startup with a clear message that does not include the URL.
- **Where it is stored.** `app.state.db_target`, set in the lifespan handler. There is no module-level cache, so each `with TestClient(app)` parses again.
- **Same-database comparison** (used by the test safety check, section 10): compare host, port and database name, after normalizing `postgres://` to `postgresql://`, treating `localhost`, `127.0.0.1` and `::1` as one host, and treating a missing port as 5432. Different host names that resolve to the same server are not detected; this is a known limit.

## 4. The adapter (`db.py`)

Routers stop importing `sqlite3`. `get_db` yields a connection object with this interface:

- `execute(sql, params=())` returns a result with `fetchone()`, `fetchall()` and `rowcount`. Rows behave like dicts. SQL is written with `?` placeholders.
- `commit()`, `rollback()`, `close()`.

Behavior:

- **Placeholders.** On PostgreSQL, `?` becomes `%s`. On both backends, `execute` raises a clear programming error if the SQL contains a literal `%`, so a mistake shows up in the default SQLite run.
- **SQLite connection.** As today: `mode=rw`, `check_same_thread=False`, `foreign_keys = ON`, dict-like rows.
- **PostgreSQL connection.** `connect_timeout=5`, dict rows, and `-c lock_timeout=5000` appended to any `options` already in the URL. The adapter never replaces existing `options`; the test fixtures rely on `-csearch_path=…` surviving.
- **Exceptions.** The adapter defines `DatabaseUnavailable` and `IntegrityViolation`. `db.py` knows nothing about HTTP.

## 5. Error handling

Translation applies to `connect`, `execute` and `commit`.

| Event | Adapter action | Result |
|---|---|---|
| Any failure while opening a PostgreSQL connection | log, raise `DatabaseUnavailable` | 503 with `Retry-After: 5` |
| SQLite `BUSY`, `LOCKED`, `CANTOPEN` (entry 6) | log, raise `DatabaseUnavailable` | 503 |
| PostgreSQL SQLSTATE `08*`, `57P01`, `57P02`, `57P03`, `53300`, `55P03`, `40001`, `40P01` | log, raise `DatabaseUnavailable` | 503 |
| PostgreSQL `OperationalError` not in that list, and `conn.broken` is true | log, raise `DatabaseUnavailable` | 503 |
| Integrity error (SQLite `IntegrityError`, PostgreSQL class `23`) | roll back, then raise `IntegrityViolation` | the route's existing 409 or follow-up |
| `UnicodeEncodeError` (lone surrogate) | pass through | existing 422 handler |
| Anything else | pass through | 500, traceback logged by the server |

Notes on the table:

- **Connect time.** libpq gives no SQLSTATE while connecting. Verified against PostgreSQL 17 with psycopg 3.3.8: wrong password, unknown user, missing database and a closed port all raise `OperationalError` with `sqlstate=None`. So every connect failure is 503, with no `pgconn` inspection and no TCP probe. This matches SQLite today, where a missing file (`SQLITE_CANTOPEN`) returns 503.
- **Connection lost after connecting.** Verified: after a server stop, a crash, a terminated backend or a cut socket, `conn.broken` is true, and it stays false for ordinary query errors (`42P01`, `23505`). The graceful stop gives `57P01`; the crash and the cut socket give no SQLSTATE.
- **Rollback before `IntegrityViolation`.** `plots.py` (create and update) runs `check_references` again on the same connection after an integrity error. On PostgreSQL an aborted transaction fails every later query, which would turn a 409 or 404 into a 500. The rollback is harmless on SQLite. If the rollback itself fails because the connection is gone, the adapter raises `DatabaseUnavailable`.
- **Foreign-key and unique violations.** Deleting a farm that still has plots (`23503`) and a duplicate plot name (`23505`) both reach the existing 409 paths.
- **Logging.** The adapter logs only on the 503 path: exception class, SQLSTATE when there is one, and the message. It never logs `e.pgconn`, the URL or the parameters. (`e.pgconn` contains the password in clear text.) Integrity violations and NUL guards write no log line.
- **Handler.** `errors.py` has one handler for `DatabaseUnavailable` that returns 503 with `Retry-After: 5`. The `sqlite3` import leaves `errors.py` and `main.py`.

## 6. Routers

`farms.py`, `plots.py` and `catalogues.py` change only in these ways: the connection annotation, `except IntegrityViolation` instead of `except sqlite3.IntegrityError`, and the NUL guards (section 8). SQL and logic stay the same.

## 7. Schema script and demo data

- **PostgreSQL schema script.** Creates the five tables and loads the three catalogues. Types and constraints mirror `seed_registry.sh`: `TEXT COLLATE "C"` for every text column including `planting_date` and the foreign-key columns, `INTEGER`, `DOUBLE PRECISION`, the same primary keys, foreign keys and `UNIQUE (farm_id, name)`. Foreign keys have no `ON DELETE` action, as in SQLite.
- **No schema name** appears in the script, so the test fixture can run it inside a fresh `test_…` schema. There is no `IF NOT EXISTS`, so a second run fails instead of quietly mixing states. The README tells people to run it with `psql --single-transaction -v ON_ERROR_STOP=1`, so a failure leaves nothing behind.
- **Demo data file** (local and tests only). The farms and plots, with the same ids and values as `seed_registry.sh`. The production script never includes it.
- **`seed_registry.sh`** is unchanged.

## 8. NUL characters

PostgreSQL rejects `\u0000` in text; SQLite accepts it. Verified: psycopg raises `DataError` on the client with no SQLSTATE, for both INSERT and SELECT parameters.

- **Request bodies.** NUL in any text field of a request body gives 422 `VALIDATION`, "Text contains invalid characters", on both backends. The fields are the names and the reference ids `farm_id`, `crop_id`, `soil_id` and `emitter_id`. The validator lives in `validation.py`. This changes SQLite behavior: a farm name with NUL used to return 201. It is a deliberate change, recorded in entry 29.
- **Lookup values.** A NUL in a path or query id can never match a stored id. Each of the 10 id-taking sites returns today's SQLite answer before any query: 404, or `200 []` for the `farm_id` filter. The sites: `GET` on `/v1/crops/{id}`, `/v1/soils/{id}`, `/v1/emitters/{id}`; `GET`, `PATCH` and `DELETE` on `/v1/farms/{id}` and on `/v1/plots/{id}`; and `GET /v1/plots?farm_id=`. The guard is an explicit `contains_nul` check at each site. This counts as part of the identical-behavior requirement.
- **Route-walking test.** It walks `app.openapi()["paths"]` (not `app.routes`, which does not list included routers in this FastAPI version) and asserts it found exactly 10 sites, so it can never pass on an empty list. Baseline: run on SQLite before any code change, all 10 sites behaved as above.
- **Lone surrogates.** Verified: psycopg raises the built-in `UnicodeEncodeError`, which the existing handler turns into 422. The existing four surrogate cases are expected to pass unchanged on PostgreSQL.

## 9. Files

New: `config.py`, the PostgreSQL schema script, the demo data file, `.env.example` (placeholders only), and the new tests.
Changed: `db.py`, `errors.py`, `main.py`, `farms.py`, `plots.py`, `catalogues.py`, `validation.py`, `tests/conftest.py`, `pyproject.toml`, `uv.lock`, `README.md`, `docs/judgment-log.md`.

README content:

- How the database is chosen: `DATABASE_URL` forms, the unset default, and that `.env` is loaded from the service directory.
- How to run the PostgreSQL schema script: `psql --single-transaction -v ON_ERROR_STOP=1`, production with the catalogues only, and the demo data file for local use.
- How to run the PostgreSQL tests: set `TEST_DATABASE_URL`; without it they are skipped; they refuse to run against the same database as `DATABASE_URL`.
- A warning: never put a real `DATABASE_URL` in `.env.example`. It is committed and must hold placeholders only. The real `.env` stays out of git.

## 10. Testing

### Fixtures

- **SQLite (default).** Unchanged mechanism (entry 2): override `get_db` with a connection to a temp copy of `registry.db`.
- **Autouse fixture.** Sets `DATABASE_URL` to a valid SQLite URL with `monkeypatch`, so startup never reads the developer's `.env`. A real environment variable beats `.env`.
- **PostgreSQL.** Only when `TEST_DATABASE_URL` is set; otherwise skipped. Each test creates a schema whose name starts with `test_`, runs the schema script and the demo data inside it, and drops it afterwards. The fixture sets `DATABASE_URL` to the test URL plus `options=-csearch_path=<schema>`, so every per-request connection uses that schema, and the real `get_db` runs. A fixture drops only the schema it created itself, by exact name, never by pattern.
- **Backend parametrization.** The `client` fixture is parametrized over `sqlite` and `postgres`. PostgreSQL has its own variants of the unavailable, locked and broken-schema fixtures: a closed port; a row lock held by a second connection (503 within about 5 seconds); a dropped table (500).

### Same-database safety check

The autouse fixture overwrites `DATABASE_URL`, so comparing `TEST_DATABASE_URL` with `os.environ["DATABASE_URL"]` during a test would always compare against SQLite. Instead, `conftest.py` captures the developer's real `DATABASE_URL` once, at session start (in `pytest_configure`, after loading the environment and `.env` the same way the service does, and before any fixture runs), and stores it. The PostgreSQL fixtures compare `TEST_DATABASE_URL` against that stored value, using the comparison from section 3, and refuse to run on a match. If the captured value is unset or a SQLite URL, there is nothing to conflict with.

### Tests that run by default (no PostgreSQL needed)

- All existing tests, unchanged.
- Config: schemes, unset and empty, relative path against the service directory, `postgres://` alias, unknown scheme, redacted `repr`, same-database comparison, `options` appending.
- The safety check refuses when `TEST_DATABASE_URL` matches the captured developer URL, including the `localhost` versus `127.0.0.1` and missing-port cases, and does not refuse when they differ.
- Adapter: `%` rejected, `?` to `%s` translation, rollback after an integrity violation on SQLite.
- A PostgreSQL `DATABASE_URL` in the environment does not move the default fixtures off SQLite; a `.env` file with a bad scheme or a PostgreSQL URL (pointing at a closed port) does not affect the default run (`GET /v1/crops` returns 200); without the autouse variable, a bad scheme makes startup fail with no URL or password in the message.
- NUL: 422 for every body text field; the route-walking test.
- Logging: a 503 logs once, a 409 does not log, and no secret appears in the log output, including for a malformed URL that contains a secret.

### Tests that run only with `TEST_DATABASE_URL`

- The existing suite on both backends (see parametrization above), including the lone-surrogate cases.
- **Parallel tests (`tests/test_parallel.py`, 4 tests) run on both backends.** They are where PostgreSQL differs most from SQLite: real concurrency and row locks. The four tests are: 200 parallel list requests all return 200; 20 parallel creates with the same name give exactly one 201 and 19 409; 20 parallel deletes of one plot give exactly one 204 and 19 404; and a farm delete racing 19 plot creates allows only 201, 204, 404 and 409. The last one exercises the rollback-then-`check_references` path. The assertions are not loosened for PostgreSQL. If the PostgreSQL run shows a 503 or 500 in these tests, for example from a deadlock, that is a finding to investigate, not a reason to widen the allowed set. The tests use at most 20 client threads, so they stay well below PostgreSQL's default connection limit.
- Connect failures, all 503 with `Retry-After`: wrong password, missing database, unreachable server.
- Connection loss: a cut socket under an open connection (no SQLSTATE, `conn.broken`) and `pg_terminate_backend` (`57P01`), both 503.
- Integrity regression: after a violation, the follow-up `check_references` gives the right 409, 404 or 422 on create and update.
- Collation: list order with ids that differ under locale collation (mixed case and punctuation), on both backends.
- Drift: all five tables of the SQLite seed compared with the PostgreSQL scripts.
- Connection settings: `lock_timeout` is 5 seconds and `search_path` survives (options are appended, not replaced).
- The schema script fails on a second run.
- NUL lookups (the 10 sites) and NUL in bodies, on PostgreSQL.

### Final verification

Run the default suite, then the PostgreSQL run against the local throwaway container (`registry-pg-test` on port 55432), and report both outputs as they come out.

## 11. Judgment log

Every entry is one decision, in the existing format (Suggested / Decided / Why). Outdated text in existing entries is edited in place, with no "Update:" notes. Entries 1, 2 and 11 change; entries 3 to 10 and 12 to 16 stay exactly as they are. Entries 17 to 33 are new. The entries are written during implementation, from the text below.

### Edits to existing entries

Only the lines named here change. The other lines of each entry stay as written.

**Entry 1** (database failures are classified in `db.py`; `errors.py` turns them into 503). Replace the Decided line with:

- **Decided:** `db.py` classifies the driver's errors and raises its own `DatabaseUnavailable`. `errors.py` has the exception handler that turns it into 503. `db.py` knows nothing about HTTP.

**Entry 2** (the environment variable part is removed). Replace the Decided and Why lines with:

- **Decided:** use the defaults, with one change. The SQLite tests override the database dependency to point at a temporary copy.
- **Why:** tests must not change the real `registry.db`.

**Entry 11** (the driver's error is now translated by the adapter). Replace the Decided line with:

- **Decided:** rely on the UNIQUE constraint and turn `IntegrityViolation` into 409.

### 17. DATABASE_URL and the .env file

- **Suggested:** the agent proposed that the URL scheme picks the backend (`postgresql://` for PostgreSQL, `sqlite:///path` for SQLite), and that an unset variable means the local `registry.db`.
- **Decided:** accepted, with four additions: a relative SQLite path resolves against the service directory, an empty value counts as unset, both `postgresql://` and `postgres://` are accepted, and the password is never shown. `.env` is loaded with python-dotenv from the service directory, and a real environment variable wins over the file. The URL is parsed at app startup and stored on `app.state`. A committed `.env.example` holds placeholders only.
- **Why:** the task requires `DATABASE_URL` explicitly. An unset variable means SQLite, so local runs and the default tests need no configuration. Parsing at startup makes a bad URL visible at deploy, and `app.state` (not a module-level cache) keeps one test from inheriting another test's database.

### 18. A thin adapter over raw SQL, not an ORM

- **Suggested:** the agent compared three approaches: a thin adapter with raw SQL, SQLAlchemy Core, and separate code for each database.
- **Decided:** the thin adapter. Routers keep their SQL with `?` placeholders, and the only new database dependency is `psycopg`.
- **Why:** identical behavior is easiest to keep when one place translates errors and placeholders. SQLAlchemy Core means rewriting all the SQL and a heavier dependency. Separate code per database doubles the code and the risk of drift.

### 19. Reject a literal % in SQL, on both backends

- **Suggested:** the agent's adapter translated `?` to `%s` for PostgreSQL and did not mention `%`.
- **Decided:** `execute` raises a clear programming error when the SQL contains `%`, on both backends.
- **Why:** psycopg treats `%` as special, so a literal one would break later in a confusing way. Checking on SQLite too means the default test run catches the mistake before production does.

### 20. PostgreSQL column types mirror SQLite

- **Suggested:** the agent offered three options: mirror SQLite, use native types (`DATE`, `NUMERIC`, `UUID`), or use `DATE` for `planting_date` only.
- **Decided:** mirror SQLite: `TEXT`, `INTEGER`, `DOUBLE PRECISION`. Native types are a non-goal.
- **Why:** psycopg then returns `str`, `int` and `float`, as sqlite3 does, so no conversion code is needed and behavior cannot drift. Validation already happens in Pydantic. Native types can be a separate, later task.

### 21. COLLATE "C" on every TEXT column

- **Suggested:** the type mapping in entry 20 said nothing about sort order. Review found that PostgreSQL uses the database's locale collation by default, which can order ids differently from SQLite's byte order.
- **Decided:** every `TEXT` column in the PostgreSQL schema is `COLLATE "C"`. A test checks list order on both backends, with ids that differ under locale ordering (mixed case and punctuation).
- **Why:** every list endpoint uses `ORDER BY id`, so a different order would be a visible behavior difference.

### 22. The PostgreSQL schema is a script run by hand, never on startup

- **Suggested:** the open question was whether the schema already exists in production or the service must create it.
- **Decided:** the tables do not exist. The service ships a schema script, run by hand as one transaction, that creates the tables and loads only the catalogues (crops, soils, emitters). Demo farms and plots are in a separate file for local use and tests. The script has no `IF NOT EXISTS` and no schema name. A test compares the SQLite seed and the PostgreSQL scripts, table by table.
- **Why:** a production schema change should be deliberate, and creating tables at startup would hide failures and need write rights at runtime. Demo data must never reach production. A second run should fail loudly. With no schema name, the test fixture can run the same script in its own schema. The comparison test stops the two copies of the catalogues from drifting apart.

### 23. One connection per request; a pool is deferred

- **Suggested:** the agent offered a connection per request, a pool for PostgreSQL only, or a pool for both.
- **Decided:** one connection per request, opened and closed in `get_db`, on both backends. A pool can be added behind `get_db` if `scripts/measure_p95.py` shows a real problem.
- **Why:** it is the smallest change and keeps the structure as it is. A pool adds a dependency, sizing, a lifecycle and a second code path, and nothing shows yet that it is needed.

### 24. Connect and lock timeouts on PostgreSQL

- **Suggested:** the agent's per-request connection used PostgreSQL's defaults.
- **Decided:** `connect_timeout` of 5 seconds, and `lock_timeout` of 5 seconds on every connection, appended to any `options` already in the URL and never replacing them.
- **Why:** without a connect timeout an unreachable server can hang for about two minutes instead of returning 503 quickly. SQLite waits 5 seconds for a lock and then returns `SQLITE_BUSY`, which becomes 503, but PostgreSQL waits forever by default, so a locked row would never give 503.

### 25. Which PostgreSQL errors return 503, after the connection is open

- **Suggested:** the agent proposed the same split as entry 6, by SQLSTATE: `08*`, `57P01`, `57P02`, `57P03`, `53300`, `55P03`, `40001` and `40P01` return 503 with `Retry-After`, and everything else returns 500.
- **Decided:** accepted, plus one rule: an `OperationalError` outside that list returns 503 when `conn.broken` is true.
- **Why:** only cases where a retry can help should return 503, as in entry 6. A dropped connection can arrive without a SQLSTATE. Checked against PostgreSQL 17: a stopped server, a killed server, a terminated backend and a cut socket all leave `conn.broken` true, while ordinary errors (`42P01`, `23505`) leave it false.

### 26. Every failure while opening the connection returns 503

- **Suggested:** the agent proposed that wrong password (`28*`) and missing database (`3D000`) return 500, with the argument of entry 6, because a retry cannot fix them.
- **Decided:** reversed for connect time. Any failure while opening the connection returns 503 with `Retry-After`: wrong password, unknown user, missing database, unreachable server, server starting up. There is no `pgconn` heuristic and no TCP probe.
- **Why:** checked against PostgreSQL 17 with psycopg 3.3.8: all four connect failures raise `OperationalError` with `sqlstate=None`, so any split would rely on fragile internals. It also matches SQLite, where a missing file (`SQLITE_CANTOPEN`) returns 503. That is a pre-existing SQLite choice and is not being changed. The cost is that a misconfiguration looks like an outage to clients, so the real cause must be in the server log (entry 27).

### 27. Log only on the 503 path, and never log secrets

- **Suggested:** the agent noted that the 503 handler wrote no log line, so the real cause of a database outage would be invisible.
- **Decided:** the adapter logs only when it raises `DatabaseUnavailable`: exception class, SQLSTATE when there is one, and the message. It never logs `e.pgconn`, the URL or the parameters. Integrity violations and the NUL guards write no log line.
- **Why:** the log is where whoever runs the service finds a misconfiguration (entry 26). `e.pgconn` contains the password in clear text, and libpq messages include host and user. A 409 for a duplicate name is a normal client answer and should not write a warning each time.

### 28. Roll back before raising IntegrityViolation

- **Suggested:** review found that after an `IntegrityError`, `plots.py` (create and update) runs `check_references` again on the same connection.
- **Decided:** the adapter rolls back as soon as it catches an integrity violation, before it raises `IntegrityViolation`. A test covers create and update, on both backends. If the rollback fails because the connection is gone, the adapter raises `DatabaseUnavailable`.
- **Why:** on PostgreSQL an aborted transaction fails every later query, which would turn a 409 or 404 into a 500. The rollback is harmless on SQLite, so there is one code path.

### 29. NUL in request body text returns 422, on both backends

- **Suggested:** the open question was that PostgreSQL rejects `\u0000` in text while SQLite accepts it, so a farm name with NUL returns 201 today and would fail on PostgreSQL.
- **Decided:** NUL in any text field of a request body (the names and `farm_id`, `crop_id`, `soil_id`, `emitter_id`) returns 422 `VALIDATION`, "Text contains invalid characters", on both backends. On SQLite this changes 201 to 422.
- **Why:** it is the only option that gives identical behavior on both backends. A NUL in a name is corrupt data, and nothing existing tests or documents it. The change is deliberate and recorded here on purpose.

### 30. NUL in a path or query id keeps today's answer, without querying

- **Suggested:** a NUL in a lookup value is also sent to the database as a parameter. On SQLite today it gives 404 (or `200 []` for the `farm_id` filter), and on PostgreSQL psycopg would raise `DataError` and the request would become a 500.
- **Decided:** each of the 10 id-taking sites returns today's SQLite answer before any query, through an explicit `contains_nul` check. A route-walking test over `app.openapi()["paths"]` asserts exactly 10 sites. The guard counts as part of the identical-behavior requirement.
- **Why:** a value with NUL can never match a stored id. An explicit guard keeps the behavior visible in each route, unlike a guard in the adapter, which would also silence real stores. The test uses the OpenAPI schema because `app.routes` does not list included routers in this FastAPI version, and it asserts the count, so it can never pass on an empty list.

### 31. The default test run stays on SQLite, and entry 2's override stays

- **Suggested:** the agent first described fixtures that set `DATABASE_URL`, which differed from entry 2's mechanism.
- **Decided:** SQLite fixtures keep overriding `get_db` with a temp copy of `registry.db`. One autouse fixture sets `DATABASE_URL` to a SQLite URL so startup never reads the developer's `.env`. Tests use PostgreSQL only through `TEST_DATABASE_URL`, never through `DATABASE_URL`. Tests prove that a PostgreSQL URL in the environment, and a bad or PostgreSQL URL in `.env`, do not change the default run.
- **Why:** the requirement is that the default run uses SQLite only, and a developer's `.env` may hold a PostgreSQL URL. A real environment variable beats `.env`, so the app needs no test-only branch.

### 32. PostgreSQL test isolation, and the same-database safety check

- **Suggested:** the agent offered a fresh schema per test, truncating and reseeding the same tables, or a new database per test.
- **Decided:** one schema per test, named with a fixed `test_` prefix. The fixture runs the schema script and the demo data inside it, puts `options=-csearch_path=<schema>` in the URL it gives the app, and drops only the schema it created, by exact name. The tests run only when `TEST_DATABASE_URL` is set, and refuse to run when it points at the same database as the developer's real `DATABASE_URL`. That value is captured once at session start, before any fixture changes it, and compared by host, port and database name.
- **Why:** a schema per test is isolated, can run in parallel, needs no extra privileges and exercises the schema script itself. The safety check keeps the tests away from a production database. Capturing the URL early matters, because the autouse fixture overwrites the variable, and a later comparison would always be against SQLite.

### 33. The parallel tests run on both backends

- **Suggested:** the open question was whether `tests/test_parallel.py` should run on PostgreSQL.
- **Decided:** all four tests run on both backends, with the assertions unchanged. A 503 or 500 there is a finding to investigate, not a reason to widen the allowed set.
- **Why:** real concurrency and row locks are where PostgreSQL differs most from SQLite, and the farm-delete race exercises the rollback-then-`check_references` path (entry 28).

## 12. Non-goals and deferred

- Native PostgreSQL types: a possible later task.
- A connection pool: add behind `get_db` if `scripts/measure_p95.py` shows a real problem.
- Detecting different host names that resolve to the same server in the safety check.
- A `57P03` (server starting up) reproduction: not tried. At connect time it is covered by the any-connect-failure rule; after connecting it is in the SQLSTATE list.
