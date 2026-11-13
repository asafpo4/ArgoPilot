# Registry on SQLite and PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `registry-service` runs on SQLite (local, tests) or PostgreSQL (production), chosen by `DATABASE_URL`, with identical endpoint behavior.

**Architecture:** `config.py` parses `DATABASE_URL` at app startup into a target stored on `app.state`. `db.py` hands routers one connection interface (`?` placeholders, dict rows) with a SQLite and a PostgreSQL implementation. Each implementation translates driver errors into `DatabaseUnavailable` or `IntegrityViolation`, which `errors.py` and the routers handle. The existing test suite runs on both backends through a parametrized fixture.

**Tech Stack:** Python 3.12+, FastAPI, sqlite3, psycopg 3 (`psycopg[binary]~=3.3`), python-dotenv, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-11-registry-postgres-design.md` (section numbers below refer to it). Read it first. All paths are relative to `services/registry-service/`; run every command from that folder.

## Global Constraints

- Work on branch `p1-postgres`. Commit locally after each task. **Never push** (judgment-log entry 4).
- End every commit message with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Endpoints, response shapes, status codes and the SQL stay the same. The only deliberate behavior change: NUL in a request-body text field returns 422 instead of 201 (spec section 8).
- Default `uv run pytest` uses SQLite only and needs no PostgreSQL. PostgreSQL tests run only when `TEST_DATABASE_URL` is set, and are skipped otherwise.
- Baseline before any change: `uv run pytest -q` gives `145 passed`. Every task keeps these passing.
- PostgreSQL connection: `connect_timeout=5`; `-c lock_timeout=5000` appended to any existing `options`, never replacing them. 503 responses carry `Retry-After: 5` and detail `Database unavailable`.
- 503 SQLSTATEs after connecting: class `08`, `57P01`, `57P02`, `57P03`, `53300`, `55P03`, `40001`, `40P01`, plus any `OperationalError` with `conn.broken` true. Every failure while opening the connection is 503. Everything else is 500.
- PostgreSQL schema: `TEXT COLLATE "C"` for every text column, `INTEGER`, `DOUBLE PRECISION`, no schema name, no `IF NOT EXISTS`.
- NUL detail text is exactly `Text contains invalid characters` (422, code `VALIDATION`).
- Test schemas start with `test_`; a fixture drops only the schema it created, by exact name.
- Logs and error messages never contain a database password, the full URL, `e.pgconn` or SQL parameters. Log only on the 503 path.
- Local PostgreSQL for tests: throwaway container `registry-pg-test` (already running), `TEST_DATABASE_URL=postgresql://postgres:PASSWORD@127.0.0.1:55432/registry`. Docker client: `"/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"` (plain `docker` is denied in WSL for now). Do not touch other containers.

## Review Focus

Inputs the spec implies but its tasks would not otherwise test. Each has its test in the named task.

1. `DATABASE_URL` that is whitespace-only, `sqlite://` with no path, or an upper-case scheme (`POSTGRESQL://`): whitespace counts as unset, no-path SQLite is a clear error, upper case is accepted. (Task 1)
2. A password with special characters (`p@ss:w/rd`, URL-encoded in the URL) never appears in `repr`, `str`, error messages or the log. (Tasks 1 and 5)
3. Unicode names (Hebrew, emoji) and a 10 000-character name round-trip identically on both backends. (Task 9)
4. SQL metacharacters in names and path ids (`'; DROP TABLE farms; --`) are stored and looked up as plain text. (Task 9)
5. Floats like `0.1`, `1e-7` and `123456789.123456789` come back from PostgreSQL exactly as from SQLite. (Task 9)

---

### Task 1: Dependencies and `config.py`

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `config.py`, `tests/test_config.py`

**Interfaces:**
- Produces, in `config.py`:
  - `SERVICE_DIR: Path`, `DEFAULT_SQLITE_PATH: Path` (`SERVICE_DIR / "registry.db"`)
  - `class ConfigError(Exception)`
  - `@dataclass(frozen=True) class SqliteTarget: path: Path`
  - `@dataclass(frozen=True) class PostgresTarget: url: str` (url normalized to `postgresql://`; `__repr__` and `__str__` show the password as `***`)
  - `parse_database_url(value: str | None, base_dir: Path = SERVICE_DIR) -> SqliteTarget | PostgresTarget`
  - `load_environment(env_file: Path | None = None) -> None` (python-dotenv, `override=False`, default `SERVICE_DIR / ".env"`; also called once when `config` is imported)
  - `same_database(url_a: str | None, url_b: str | None) -> bool` (spec section 3 rules; `None` or a SQLite URL gives `False`)

- [ ] **Step 1: Add dependencies.** `uv add "psycopg[binary]~=3.3" python-dotenv`. Run `uv run pytest -q`; expect `145 passed`.
- [ ] **Step 2: Write `tests/test_config.py` (all failing).** Test names and assertions:
  - `test_unset_empty_and_whitespace_use_default_sqlite`: `None`, `""`, `"   "` each give `SqliteTarget(DEFAULT_SQLITE_PATH)`.
  - `test_relative_sqlite_path_resolves_against_base_dir`: `parse_database_url("sqlite:///x.db", tmp_path) == SqliteTarget(tmp_path / "x.db")`; `sqlite:////abs/y.db` gives `/abs/y.db`.
  - `test_sqlite_url_without_path_is_an_error`: `sqlite://` and `sqlite:///` raise `ConfigError`.
  - `test_both_postgres_schemes_and_any_case`: `postgres://`, `postgresql://`, `POSTGRESQL://` give `PostgresTarget` whose `url` starts with `postgresql://`.
  - `test_unknown_or_malformed_url_raises_without_secret`: `mysql://u:s3cret@h/db` and `not a url s3cret` raise `ConfigError`; `"s3cret"` not in `str(exc)`.
  - `test_password_with_special_characters_is_redacted`: url `postgresql://u:p%40ss%3Aw%2Frd@h/db`; none of `p@ss`, `p%40ss`, `w/rd` in `repr(t)` or `str(t)`; `***` is.
  - `test_same_database_rules`: equal when host/port/dbname match after scheme normalization; `localhost`, `127.0.0.1`, `::1` equal; missing port equals 5432; different dbname, host or port is not equal; `None` and `sqlite:///a.db` give `False`.
  - `test_load_environment_fills_missing_but_never_overrides`: temp `.env` with `A=1` and `B=2`; with `B` already set, afterwards `A=="1"`, `B` unchanged (use `monkeypatch`).
- [ ] **Step 3: Run `uv run pytest tests/test_config.py -q`.** Expect import failure or FAIL.
- [ ] **Step 4: Implement `config.py`** per Interfaces. Use `urllib.parse`; build error messages from the scheme only, never the URL.
- [ ] **Step 5: Run `uv run pytest -q`.** Expect all pass (145 plus the new tests).
- [ ] **Step 6: Commit** `git add pyproject.toml uv.lock config.py tests/test_config.py` with message `Add DATABASE_URL parsing and psycopg and dotenv dependencies`.

---

### Task 2: The adapter on SQLite; routers, errors, conftest migrated (behavior unchanged)

**Files:**
- Modify: `db.py`, `errors.py`, `main.py`, `farms.py`, `plots.py`, `catalogues.py`, `tests/conftest.py`
- Create: `tests/test_db_adapter.py`

**Interfaces:**
- Consumes: `config.DEFAULT_SQLITE_PATH`.
- Produces, in `db.py`:
  - `class DatabaseUnavailable(Exception)`, `class IntegrityViolation(Exception)`
  - `logger = logging.getLogger("registry.db")`
  - `class Connection` (base class): `raw` (the driver connection), `execute(sql: str, params: Sequence = ()) -> Result` (cursor-like: `fetchone()`, `fetchall()`, `rowcount`, rows usable with `dict(row)`), `commit() -> None`, `rollback() -> None`, `close() -> None`. `execute` first rejects SQL containing `%` with `ValueError("SQL must not contain a literal %")`, on every backend. Hooks for subclasses: `_prepare(sql: str) -> str` and `_classify(exc: Exception) -> Literal["unavailable", "integrity", "other"]`. `execute` and `commit` call `_classify` on driver errors: `unavailable` gives `logger.warning(...)` then `DatabaseUnavailable`; `integrity` gives `rollback()` (if that fails, `DatabaseUnavailable`) then `IntegrityViolation`; `other` re-raises the original exception unchanged.
  - `class SqliteConnection(Connection)`; `connect(path: Path) -> Connection` (same options as today: `mode=rw`, `check_same_thread=False`, `foreign_keys = ON`, `sqlite3.Row`). `unavailable` means `sqlite_errorname` in `BUSY`, `LOCKED`, `CANTOPEN` (entry 6); `integrity` means `sqlite3.IntegrityError`.
  - `DB_PATH = config.DEFAULT_SQLITE_PATH`; `get_db() -> Iterator[Connection]` stays zero-argument for now (opens `connect(DB_PATH)`).
- Produces, in `errors.py`: `database_unavailable_handler(request, exc: DatabaseUnavailable)` returns 503, code `UNAVAILABLE`, detail `Database unavailable`, header `Retry-After: 5`. No `sqlite3` import remains in `errors.py` or `main.py`.

- [ ] **Step 1: Write `tests/test_db_adapter.py` (failing).** Use a temp copy of `registry.db` and `db.connect`:
  - `test_percent_in_sql_is_rejected`: `execute("SELECT '100%'")` raises `ValueError`.
  - `test_integrity_violation_rolls_back_then_raises`: insert farm `('t1','A')` uncommitted, then insert a duplicate id; expect `IntegrityViolation`; afterwards `SELECT count(*) FROM farms WHERE id='t1'` is 0 and the connection still works.
  - `test_busy_database_raises_unavailable_and_logs_once`: hold `BEGIN IMMEDIATE` on a second raw connection, `execute("PRAGMA busy_timeout = 100")`, then a write raises `DatabaseUnavailable`; `caplog` has exactly one WARNING from `registry.db`.
  - `test_missing_file_raises_unavailable`: `db.connect(tmp_path / "missing.db")` raises `DatabaseUnavailable`.
  - `test_integrity_violation_writes_no_log`: `caplog.records` is empty after a duplicate-id violation.
  - `test_other_errors_pass_through_unchanged`: `SELECT * FROM no_such_table` raises `sqlite3.OperationalError`.
  - `test_lone_surrogate_passes_through`: a parameter `"\ud800"` raises `UnicodeEncodeError`.
- [ ] **Step 2: Run `uv run pytest tests/test_db_adapter.py -q`.** Expect FAIL.
- [ ] **Step 3: Implement `db.py`** per Interfaces.
- [ ] **Step 4: Migrate the rest.** In `farms.py`, `plots.py`, `catalogues.py` change the annotation `sqlite3.Connection` to `db.Connection` and `except sqlite3.IntegrityError` to `except IntegrityViolation`; drop `import sqlite3`. In `errors.py` replace the sqlite handler and `UNAVAILABLE_SQLITE_ERRORS`. In `main.py` register `DatabaseUnavailable` instead of `sqlite3.OperationalError`. In `tests/conftest.py` change the `Iterator[sqlite3.Connection]` annotations to `Iterator[Connection]`; fixtures that use raw `sqlite3` to lock or drop a table keep doing so.
- [ ] **Step 5: Run `uv run pytest -q`.** Expect everything passes, including every existing test unchanged (503 and 500 tests in `tests/test_errors.py` included).
- [ ] **Step 6: Commit** `Add the database adapter on SQLite and move routers to it`.

---

### Task 3: Startup parsing, `app.state`, default-run isolation

**Files:**
- Modify: `main.py`, `db.py`, `tests/conftest.py`
- Create: `tests/test_startup_config.py`

**Interfaces:**
- Consumes: `config.parse_database_url`, `config.load_environment`, `config.ConfigError`, `config.SqliteTarget`, `config.PostgresTarget`.
- Produces:
  - `main.py` lifespan: sets `app.state.db_target = config.parse_database_url(os.environ.get("DATABASE_URL"))` at startup. A `ConfigError` stops startup.
  - `db.connect_target(target: SqliteTarget | PostgresTarget) -> Connection` (the PostgreSQL branch raises `NotImplementedError` until Task 5).
  - `db.get_db(request: Request) -> Iterator[Connection]`: opens `connect_target(request.app.state.db_target)`, closes after the request.
  - `tests/conftest.py`: autouse fixture `isolate_database_url` that `monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(DB_PATH))`.

- [ ] **Step 1: Write `tests/test_startup_config.py` (failing).**
  - `test_startup_stores_parsed_target_on_app_state`: inside `with TestClient(app)`, `app.state.db_target` is a `SqliteTarget`.
  - `test_each_startup_parses_again`: two successive `with TestClient(app)` blocks with different `DATABASE_URL` values (set via `monkeypatch`) give different targets.
  - `test_unknown_scheme_fails_startup_without_leaking_url`: `DATABASE_URL=mysql://u:s3cret@h/db` makes `with TestClient(app)` raise `ConfigError`; `"s3cret"` not in `str(exc)`.
  - `test_bad_dot_env_does_not_affect_default_run`: with the `client` fixture active, write a temp `.env` containing `DATABASE_URL=nonsense://x`, call `config.load_environment(path)`, then start a new `TestClient(app)` (startup must not raise) and `GET /v1/crops` returns 200.
  - `test_postgres_dot_env_does_not_affect_default_run`: same with `DATABASE_URL=postgresql://postgres:x@127.0.0.1:1/registry` (a closed port, so an attempted connection would give 503); `GET /v1/crops` returns 200.
  - `test_postgres_url_in_environment_keeps_default_fixtures_on_sqlite`: `monkeypatch.setenv("DATABASE_URL", <closed-port postgres URL>)` inside the test; `GET /v1/crops` through `client` returns 200 and `app.state.db_target` (set by the fixture's startup) is a `SqliteTarget`.
- [ ] **Step 2: Run the file.** Expect FAIL.
- [ ] **Step 3: Implement** the lifespan, `connect_target`, `get_db(request)` and the autouse fixture. The existing SQLite fixtures still override `get_db` (entry 2).
- [ ] **Step 4: Run `uv run pytest -q`.** Expect all pass.
- [ ] **Step 5: Commit** `Parse DATABASE_URL at startup and keep the default test run on SQLite`.

---

### Task 4: NUL handling (bodies and lookups)

**Files:**
- Modify: `validation.py`, `farms.py`, `plots.py`, `catalogues.py`, `errors.py`, `main.py`
- Create: `tests/test_nul_text.py`

**Interfaces:**
- Produces, in `validation.py`: `contains_nul(value: str) -> bool`; `class InvalidTextError(Exception)`; `reject_nul(value: str) -> str` (raises `InvalidTextError`); `StoredText = Annotated[str, AfterValidator(reject_nul)]`; `RequiredName` now rejects NUL before stripping. `PlotCreate` and `PlotUpdate` use `StoredText` for `farm_id`, `crop_id`, `soil_id`, `emitter_id`.
- `errors.py`: `invalid_text_handler` is registered for both `UnicodeEncodeError` and `InvalidTextError` and returns 422, code `VALIDATION`, detail `Text contains invalid characters`.

- [ ] **Step 1: Write the baseline route-walking test first, and run it before any code change.** In `tests/test_nul_text.py`: `test_nul_lookup_values_keep_todays_answers(client)` walks `app.openapi()["paths"]` (not `app.routes`: this FastAPI version hides included routers) for paths under `/v1`; every path parameter, and every query parameter ending in `_id`, receives `a%00b`. Assert exactly 10 sites are found. Expect 404 for each path-id site (PATCH sent with body `{"name": "x"}`) and `200` with `[]` for `GET /v1/plots?farm_id=a%00b`. Run `uv run pytest tests/test_nul_text.py -q`. **Expected: PASS now**, because it describes today's SQLite behavior. A failure means the spec's table of 10 sites is wrong: stop and report.
- [ ] **Step 2: Write the body tests (failing).** `test_nul_in_body_text_returns_422` parametrized over: POST `/v1/farms` `name`; PATCH `/v1/farms/<demo farm id>` `name`; POST `/v1/plots` and PATCH `/v1/plots/<North block id>` for `name`, `farm_id`, `crop_id`, `soil_id`, `emitter_id` (POST bodies otherwise valid, like `VALID_BODY` in `tests/test_parallel.py`). Send the JSON text with the six characters `\u0000` (like the existing surrogate test). Assert 422, content-type `application/problem+json`, `code == "VALIDATION"`, `detail == "Text contains invalid characters"`.
- [ ] **Step 3: Run it.** Expect FAIL (today: 201, 200 or 404/422 with other details).
- [ ] **Step 4: Implement the validator and handler.** Verify that Pydantic lets a non-`ValueError` raised in `AfterValidator` reach the app's exception handler. If it does not, raise `ValueError` subclass instead and make `validation_exception_handler` return the exact detail when `ctx["error"]` is an `InvalidTextError`.
- [ ] **Step 5: Add the 10 guards** (explicit `if contains_nul(x): raise HTTPException(404, ...)` at the top of each handler, with that route's own existing not-found detail, before any query; the `farm_id` filter in `list_plots` returns `[]`). Run the whole file: all pass.
- [ ] **Step 6: Run `uv run pytest -q`.** Expect all pass. The existing lone-surrogate tests must still pass.
- [ ] **Step 7: Commit** `Reject NUL in text and keep today's answer for NUL lookups`.

---

### Task 5: The PostgreSQL adapter

**Files:**
- Modify: `db.py`
- Create: `tests/test_db_postgres_adapter.py` (unit tests, run by default, need no server)

**Interfaces:**
- Consumes: `Connection` base class from Task 2.
- Produces, in `db.py`:
  - `PG_UNAVAILABLE_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300", "55P03", "40001", "40P01"})`
  - `translate_placeholders(sql: str) -> str` (every `?` becomes `%s`)
  - `postgres_conninfo(url: str) -> str` (sets `connect_timeout=5`; appends ` -c lock_timeout=5000` to the decoded `options` value, creating it when absent)
  - `classify_postgres_error(exc: Exception, broken: bool) -> Literal["unavailable", "integrity", "other"]`: `integrity` for `psycopg.errors.IntegrityError`; `unavailable` for SQLSTATE in the set or starting with `08`, or for `psycopg.OperationalError` when `broken`; `other` for the rest (including `DataError` and `UnicodeEncodeError`)
  - `class PostgresConnection(Connection)`: `_prepare` is `translate_placeholders`; `_classify` is `classify_postgres_error(exc, self.raw.broken)`; rows are dicts (`psycopg.rows.dict_row`)
  - `connect_postgres(url: str) -> Connection`: any `psycopg.Error` while connecting logs and raises `DatabaseUnavailable`
  - `connect_target` now handles `PostgresTarget` through `connect_postgres(target.url)`.

- [ ] **Step 1: Write the unit tests (failing).** Build exceptions directly (`psycopg.errors.AdminShutdown()`, `psycopg.OperationalError()`) and a fake raw connection with a `broken` attribute and a recording `rollback`:
  - `test_translate_placeholders`: `"a = ? AND b = ?"` becomes `"a = %s AND b = %s"`.
  - `test_conninfo_sets_timeouts_and_appends_to_existing_options`: from `postgresql://u:p@h/db?options=-csearch_path%3Dtest_ab` the result's decoded `options` is `-csearch_path=test_ab -c lock_timeout=5000` and `connect_timeout` is `5`; with no options, `options` is `-c lock_timeout=5000`.
  - `test_classification_table`: `08006`, each set member, and `AdminShutdown` give `unavailable`; `OperationalError()` with `broken=True` gives `unavailable`, with `broken=False` gives `other`; `UniqueViolation` and `ForeignKeyViolation` give `integrity`; `UndefinedTable`, `DataError()` and `UnicodeEncodeError` give `other`.
  - `test_integrity_error_rolls_back_then_raises`: fake `execute` raises `UniqueViolation`; `IntegrityViolation` is raised and `rollback` was called once.
  - `test_failed_rollback_becomes_unavailable`: rollback raises `OperationalError`; result `DatabaseUnavailable`.
  - `test_commit_errors_are_translated`: a fake `commit` raising `SerializationFailure` gives `DatabaseUnavailable`.
  - `test_unavailable_log_never_contains_password`: connecting to `postgresql://u:p%40ss%3Aw%2Frd@127.0.0.1:1/db` raises `DatabaseUnavailable`; no record in `caplog.text` contains `p@ss`, `p%40ss` or `w/rd`; exactly one WARNING.
  - `test_other_errors_pass_through_unchanged`: `UndefinedTable` raised by the fake is the same object that escapes.
- [ ] **Step 2: Run the file.** Expect FAIL.
- [ ] **Step 3: Implement** per Interfaces. Log only exception class, SQLSTATE and message; never format `exc.pgconn` or the URL.
- [ ] **Step 4: Run `uv run pytest -q`.** Expect all pass.
- [ ] **Step 5: Commit** `Add the PostgreSQL connection adapter`.

---

### Task 6: PostgreSQL schema script and demo data

**Files:**
- Create: `sql/postgres_schema.sql`, `sql/demo_data.sql`

**Interfaces:**
- Produces: `sql/postgres_schema.sql` (five tables plus catalogues, spec section 7; no schema name; no `IF NOT EXISTS`) and `sql/demo_data.sql` (the 2 farms and 4 plots from `seed_registry.sh`, same ids and values). Catalogue rows identical to `seed_registry.sh`: crops `tomato`/`bell-pepper`; soils `sand` 83, `loam` 175, `clay-loam` 200; emitters `dripnet-pc-0.6/1.0/1.6/2.0` with flow 0.6/1.0/1.6/2.0.

- [ ] **Step 1: Write both files.** Types mirror `seed_registry.sh`; every `TEXT` column (ids, names, `planting_date`, foreign-key columns) is `COLLATE "C"`; `UNIQUE (farm_id, name)`; foreign keys without `ON DELETE`.
- [ ] **Step 2: Verify the schema script in a scratch schema** (this is a manual check; the automated tests come in Task 7). With `D="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"`:
  - Create: `"$D" exec registry-pg-test psql -U postgres -d registry -c "CREATE SCHEMA scratch_check"`.
  - Run: `"$D" exec -i -e PGOPTIONS="-c search_path=scratch_check" registry-pg-test psql -U postgres -d registry -v ON_ERROR_STOP=1 --single-transaction < sql/postgres_schema.sql`. Expect `COMMIT`-style success with no error; then the same for `sql/demo_data.sql`.
  - Check: `... -c "SELECT count(*) FROM farms"` shows 2, plots 4.
  - Second run of the schema script must fail with `already exists`.
  - Clean up only what you created: `... -c "DROP SCHEMA scratch_check CASCADE"`.
- [ ] **Step 3: Check the ordering premise for Task 9.** `"$D" exec registry-pg-test psql -U postgres -d registry -c "SELECT array_agg(x ORDER BY x) FROM unnest(ARRAY['a-1','A-2','a_3','B-1','b-2']) x"`. Byte order would be `A-2, B-1, a-1, a_3, b-2`. Expect a different order from the default collation. If it already is byte order, tell me before continuing, because the Task 9 collation test would prove nothing.
- [ ] **Step 4: Commit** `Add the PostgreSQL schema script and demo data`.

---

### Task 7: PostgreSQL test infrastructure

**Files:**
- Create: `tests/pg_support.py`, `tests/test_pg_infrastructure.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces, in `tests/pg_support.py`:
  - `SCHEMA_PREFIX = "test_"`
  - `capture_developer_database_url(environ: Mapping[str, str]) -> str | None` (value of `DATABASE_URL`, empty counted as `None`)
  - `check_not_developer_database(test_url: str, developer_url: str | None) -> None` (uses `config.same_database`; raises `pytest.fail(..., pytrace=False)` with a message starting `refusing to run` on a match)
  - `with_url_parts(url: str, *, password: str | None = None, dbname: str | None = None, port: int | None = None) -> str`
  - `with_options(url: str, options: str) -> str` (adds `options=<options>`)
- Produces, in `tests/conftest.py`:
  - `pytest_configure` stores `pg_support.DEVELOPER_DATABASE_URL = capture_developer_database_url(os.environ)` **after `import config` (which loads `.env`) and before any fixture runs**.
  - session fixture `pg_base_url` (skips unless `TEST_DATABASE_URL`; runs `check_not_developer_database`).
  - function fixture `pg_schema` (creates `test_<uuid hex>`, runs `sql/postgres_schema.sql` and `sql/demo_data.sql` with `search_path` set to it, yields the name, drops exactly that schema afterwards).
  - function fixture `pg_app_url` (the base URL plus `options=-csearch_path=<schema>`).
  - parametrized fixture `database(request)` with params `["sqlite", "postgres"]` yielding `TestDatabase(backend: str, connect: Callable[[], Connection])`. `client` now depends on `database`: for `sqlite` it works as today; for `postgres` it sets `DATABASE_URL` to `pg_app_url` with `monkeypatch`, does not override `get_db`, and uses the real one. `unavailable_client` and `broken_schema_client` are parametrized the same way (PostgreSQL variants: URL on closed port `1`; `DROP TABLE crops CASCADE` inside the test schema). `locked_client` and `broken_client` stay as they are (SQLite-only and backend-independent).

- [ ] **Step 1: Write `tests/test_pg_infrastructure.py` (failing).**
  - `test_capture_ignores_empty_and_returns_value`.
  - `test_check_refuses_on_match`: `check_not_developer_database` fails for equal URLs, for `localhost` against `127.0.0.1`, and for a missing port against `:5432`; it does nothing for a different database name, or when the developer URL is `None` or `sqlite:///x.db`.
  - `test_session_start_capture_happens_before_fixtures` (end to end, in a subprocess with `sys.executable -m pytest`): environment `DATABASE_URL=TEST_DATABASE_URL=postgresql://u:p@nohost.invalid:5432/prod`, running `tests/test_farms.py::test_list_farms_returns_both_seeded_farms -k postgres`; assert the output contains `refusing to run` and no connection to `nohost.invalid` was attempted (no `could not translate host name`).
  - `test_schema_script_fails_on_second_run` and `test_pg_schema_contains_demo_data` (PostgreSQL only; skipped without `TEST_DATABASE_URL`): in a `pg_schema`, running the schema script again raises; `farms` has 2 rows and `plots` has 4.
  - `test_catalogue_and_demo_rows_match_sqlite_seed` (PostgreSQL only): for all five tables, rows from a SQLite temp copy equal rows from the `pg_schema`, compared as sorted tuples.
- [ ] **Step 2: Run `uv run pytest tests/test_pg_infrastructure.py -q`.** Expect FAIL.
- [ ] **Step 3: Implement** `pg_support.py` and the conftest changes. Keep SQLite `client` behavior identical.
- [ ] **Step 4: Run the default suite** `uv run pytest -q`. Expect all pass, with every test that uses `client` reported twice (`[sqlite]` passes, `[postgres]` skipped).
- [ ] **Step 5: Run against PostgreSQL** `TEST_DATABASE_URL=postgresql://postgres:PASSWORD@127.0.0.1:55432/registry uv run pytest -q`. This runs the whole existing suite, the four `tests/test_parallel.py` tests and the four lone-surrogate cases on PostgreSQL. Expect all to pass. **A failure here is a finding: report it with the output, and do not weaken an assertion or widen an allowed status set.**
- [ ] **Step 6: Confirm no leftovers:** `"$D" exec registry-pg-test psql -U postgres -d registry -c "\dn"` lists no `test_*` schemas.
- [ ] **Step 7: Commit** `Add PostgreSQL test fixtures, the safety check and backend parametrization`.

---

### Task 8: PostgreSQL failure behavior

**Files:**
- Create: `tests/test_postgres_failures.py` (all tests skip without `TEST_DATABASE_URL`)

**Interfaces:**
- Consumes: `pg_support.with_url_parts`, `pg_base_url`, `pg_schema`, `pg_app_url`, `db.connect_postgres`.

- [ ] **Step 1: Write the tests.** Each builds a `TestClient(app, raise_server_exceptions=False)` with `DATABASE_URL` set by `monkeypatch`, calls `GET /v1/crops`, and asserts status, content-type `application/problem+json`, `Retry-After: 5`, code `UNAVAILABLE`, detail `Database unavailable`, unless stated:
  - `test_wrong_password_returns_503`, `test_unknown_database_returns_503`, `test_unreachable_server_returns_503` (port `1`).
  - `test_row_lock_returns_503_within_lock_timeout`: a second connection runs `UPDATE farms SET name = name WHERE id = '<demo cooperative id>'` without committing; `PATCH /v1/farms/<that id>` takes between 4.5 and 9 seconds and returns 503 with `Retry-After: 5`; the second connection rolls back afterwards. (A plain INSERT does not conflict on PostgreSQL, so the SQLite locked test is not reused.)
  - `test_cut_socket_returns_503`: override `get_db` with a function that opens `connect_postgres(pg_app_url)`, runs `SELECT 1`, shuts the socket down (`socket.socket(fileno=os.dup(conn.raw.fileno())).shutdown(socket.SHUT_RDWR)`), and yields it; `GET /v1/crops` returns 503.
  - `test_terminated_backend_returns_503`: same, but the backend is ended with `pg_terminate_backend(<pid>)` from a second connection.
  - `test_failure_log_has_cause_and_no_password`: after the wrong-password request, `caplog` has one WARNING from `registry.db` mentioning `password authentication failed` and not containing the password.
- [ ] **Step 2: Run** `TEST_DATABASE_URL=postgresql://postgres:PASSWORD@127.0.0.1:55432/registry uv run pytest tests/test_postgres_failures.py -q`. Expect all pass; investigate any failure rather than changing the expectation.
- [ ] **Step 3: Run the default suite** `uv run pytest -q`; expect these tests skipped and everything else passing.
- [ ] **Step 4: Commit** `Test PostgreSQL failure behavior`.

---

### Task 9: Data behavior on both backends

**Files:**
- Create: `tests/test_backend_parity.py`

**Interfaces:**
- Consumes: parametrized `client`, `database` (`database.connect()` opens an adapter connection to the same database the client uses).

- [ ] **Step 1: Write the tests (they run on `[sqlite]` by default and on `[postgres]` with `TEST_DATABASE_URL`).**
  - `test_integrity_violation_then_reference_check_gives_404`: monkeypatch `plots.check_references` so its first call does nothing and later calls are real; `POST /v1/plots` with an unknown `farm_id` fails the insert on a foreign key, then the second check returns 404 `Farm not found` (without the rollback, PostgreSQL would answer 500).
  - `test_duplicate_plot_name_gives_409_on_create_and_update`: create twice with the same name gives 409; PATCH a plot to another plot's name in the same farm gives 409; afterwards `GET /v1/plots` still works (200).
  - `test_farm_delete_with_plots_gives_409`.
  - `test_list_order_is_byte_order`: insert farms through `database.connect()` with ids `["a-1", "A-2", "a_3", "B-1", "b-2"]`, commit; `GET /v1/farms` ids equal `sorted(all ids, key=str.encode)` including the two demo farms.
  - `test_unicode_and_long_names_round_trip`: farm names `"חווה 🌱"` and `"x" * 10_000` come back identical from POST and from GET.
  - `test_sql_metacharacters_are_plain_text`: farm name `"'; DROP TABLE farms; --"` round-trips; `GET /v1/farms/%27%3B%20DROP%20TABLE%20farms%3B%20--` returns 404; `GET /v1/farms` still returns the other farms.
  - `test_floats_round_trip_exactly`: plots created with `area_m2` of `0.1`, `1e-7` and `123456789.123456789` read back with equal values.
  - `test_connection_uses_expected_settings` (PostgreSQL only): through `database.connect()`, `SHOW lock_timeout` is `5s`; `SHOW search_path` starts with the test schema (options were appended, not replaced).
- [ ] **Step 2: Run on SQLite** `uv run pytest tests/test_backend_parity.py -q`. Expect all `[sqlite]` pass. A `[sqlite]` failure means the test is wrong (it describes today's behavior): fix the test.
- [ ] **Step 3: Run on PostgreSQL** with `TEST_DATABASE_URL` set. Expect all pass. Also rerun `tests/test_nul_text.py` there: the route-walking test must pass on `[postgres]` (10 sites, no 500).
- [ ] **Step 4: Run the whole PostgreSQL suite once more,** then `"$D" exec registry-pg-test psql -U postgres -d registry -c "\dn"` to confirm no `test_*` schema remains.
- [ ] **Step 5: Commit** `Test data behavior on both backends`.

---

### Task 10: Documentation, judgment log, final verification

**Files:**
- Create: `.env.example`
- Modify: `README.md`, `docs/judgment-log.md`

- [ ] **Step 1: `.env.example`**: commented examples only, placeholders and no real password: `# DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME`, `# DATABASE_URL=sqlite:///registry.db`, `# TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/TEST_DBNAME`.
- [ ] **Step 2: `README.md`**: add the four content items listed under "README content" in spec section 9 (how the database is chosen; running the schema script with `psql --single-transaction -v ON_ERROR_STOP=1`; running the PostgreSQL tests; the warning never to put a real `DATABASE_URL` in `.env.example`). Update the first paragraph, which says "built with FastAPI and SQLite", and the test note ("work on a copy of the database").
- [ ] **Step 3: `docs/judgment-log.md`**: edit entries 1, 2 and 11 in place, with no "Update:" notes, using the replacement lines in spec section 11 ("Edits to existing entries"). Then append entries 17 to 33 exactly as written in spec section 11, with `##` headings (the log uses `## N. Title`).
- [ ] **Step 4: Check the log.** Run:

  ```bash
  python3 - <<'EOF'
  import re, subprocess
  old = subprocess.check_output(["git", "show", "HEAD:./docs/judgment-log.md"], text=True)
  new = open("docs/judgment-log.md").read()
  split = lambda t: re.split(r"(?m)^(?=## \d+\. )", t)[1:]
  o, n = split(old), split(new)
  print(len(n), [i + 1 for i, (a, b) in enumerate(zip(o, n)) if a.rstrip() != b.rstrip()])
  EOF
  ```

  Expected output: `33 [1, 2, 11]`. That means 33 entries, and only entries 1, 2 and 11 differ from the committed log. Also run `grep -n "Update:" docs/judgment-log.md`; expect no output.
- [ ] **Step 5: Final verification, in order, reporting the real output of each:**
  - `uv run pytest -q` (default run, expect all passed, PostgreSQL variants skipped).
  - `DATABASE_URL=postgresql://postgres:x@127.0.0.1:1/registry uv run pytest -q` (a PostgreSQL URL in the environment; expect the same result as the default run).
  - `TEST_DATABASE_URL=postgresql://postgres:PASSWORD@127.0.0.1:55432/registry uv run pytest -q` (expect all passed, none skipped except tests that need a different setup, and say which).
  - `git status` clean; `git log --oneline` shows one commit per task; nothing pushed.
- [ ] **Step 6: Commit** `Document PostgreSQL support and record the decisions`.
