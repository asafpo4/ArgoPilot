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

- **Request bodies.** NUL in any text field of a request body gives 422 `VALIDATION`, "Text contains invalid characters", on both backends. The fields are the names and the reference ids `farm_id`, `crop_id`, `soil_id` and `emitter_id`. The validator lives in `validation.py`. This changes SQLite behavior: a farm name with NUL used to return 201. It is a deliberate change, recorded in entry 17.
- **Lookup values.** A NUL in a path or query id can never match a stored id. Each of the 10 id-taking sites returns today's SQLite answer before any query: 404, or `200 []` for the `farm_id` filter. The sites: `GET` on `/v1/crops/{id}`, `/v1/soils/{id}`, `/v1/emitters/{id}`; `GET`, `PATCH` and `DELETE` on `/v1/farms/{id}` and on `/v1/plots/{id}`; and `GET /v1/plots?farm_id=`. The guard is an explicit `contains_nul` check at each site. This counts as part of the identical-behavior requirement.
- **Route-walking test.** It walks `app.openapi()["paths"]` (not `app.routes`, which does not list included routers in this FastAPI version) and asserts it found exactly 10 sites, so it can never pass on an empty list. Baseline: run on SQLite before any code change, all 10 sites behaved as above.
- **Lone surrogates.** Verified: psycopg raises the built-in `UnicodeEncodeError`, which the existing handler turns into 422. The existing four surrogate cases are expected to pass unchanged on PostgreSQL.

## 9. Files

New: `config.py`, the PostgreSQL schema script, the demo data file, `.env.example` (placeholders only), and the new tests.
Changed: `db.py`, `errors.py`, `main.py`, `farms.py`, `plots.py`, `catalogues.py`, `validation.py`, `tests/conftest.py`, `pyproject.toml`, `uv.lock`, `README.md`, `docs/judgment-log.md`.

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

- **Entry 2.** Add an update note at the end: "Update: the 'no environment variable' part is replaced by entry 17. The rest of this entry still stands." The 12 defaults and the temp-copy test approach remain in force.
- **Entry 17 (new).** Records, with reasons:
  - The replaced part of entry 2: the original decision was right at the time, because the first task did not ask for an environment variable; this task requires `DATABASE_URL` explicitly.
  - Both backends, the URL rules, and the `.env` handling.
  - Types and `COLLATE "C"`; native types as a non-goal.
  - The connect-time rule: a first decision to give 500 for authentication and missing-database failures was reversed for connect time, because libpq gives no SQLSTATE while connecting. The evidence is the check against PostgreSQL 17 (four connect failures, all `OperationalError` with `sqlstate=None`).
  - `SQLITE_CANTOPEN` returning 503 is a pre-existing SQLite choice and is not changed.
  - Per-request connections, with the pool deferred.
  - The NUL change from 201 to 422, and the NUL lookup guard as part of identical behavior.
- All 16 existing entries stay.

## 12. Non-goals and deferred

- Native PostgreSQL types: a possible later task.
- A connection pool: add behind `get_db` if `scripts/measure_p95.py` shows a real problem.
- Detecting different host names that resolve to the same server in the safety check.
- A `57P03` (server starting up) reproduction: not tried. At connect time it is covered by the any-connect-failure rule; after connecting it is in the SQLSTATE list.
