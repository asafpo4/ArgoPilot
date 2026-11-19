# Registry on SQLAlchemy, pydantic-settings and a seed command: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move registry-service data access to SQLAlchemy Core and settings to pydantic-settings, and add one seed command for an empty PostgreSQL database, with no change in what clients see.

**Architecture:** `db.py` keeps its `Connection`/`Result` wrapper (approach A) but runs on a SQLAlchemy `Engine` with `NullPool`; routers change only their SQL strings and params (`:name`, dicts). `config.py` gets a `Settings` class and keeps today's URL validation. The 15 seed rows live once in `sql/seed_data.sql`, used by `seed_registry.sh` (SQLite) and `seeding.py` (PostgreSQL).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.1 (Core, `text`), psycopg 3 (`postgresql+psycopg`), pydantic-settings, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-15-registry-sqlalchemy-design.md` (builds on `2026-11-11-registry-postgres-design.md`).

All paths are relative to `services/registry-service/` unless they start with `/`. Run commands from that folder.

## Global Constraints

- Behavior seen by clients is unchanged: status codes, problem+json `code`s, `Retry-After: 5` on 503, the 503 vs 500 split.
- All data access (app and seed command) goes through SQLAlchemy Core; SQL stays as `sqlalchemy.text`. No ORM, no Alembic, no schema creation on startup.
- `NullPool` on both backends: one connection per request, opened and closed in `get_db` (entry 23).
- Rollback before raising `IntegrityViolation`. PostgreSQL `connect_timeout=5` and `lock_timeout=5000`, appended to any `options` already in the URL.
- No password or URL in a log line, an error message or a `repr`. SQLAlchemy exception text contains SQL and parameters: never log `str(exc)` of a SQLAlchemy exception, only the driver error (`exc.orig`) under the entry 27 rules.
- `DATABASE_URL` stays optional (unset or blank = local SQLite). A real environment variable beats `.env`. libpq's parse stays the authority for PostgreSQL URLs.
- The engine URL uses the `postgresql+psycopg` driver; `DATABASE_URL` keeps accepting `postgresql://` and `postgres://`.
- A literal `%` in SQL is safe; a literal `:` in SQL text must be `\:`.
- `seed.py` seeds PostgreSQL only and refuses a SQLite or unset target. A second run fails and rolls back.
- Rebuilding `registry.db` must give exactly the baseline rows: sha256 `5fca1040563d1f47fddc664b110a6ab3ff893164c61720bd8e7bd46b046f3797` over the output of `SELECT * FROM <t> ORDER BY id` for `crops, soils, emitters, farms, plots`, each preceded by a `-- <t>` line (the baseline is in the scratchpad, `baseline_rows.txt`, 20 lines), with the same table definitions (`baseline_schema.txt`).
- English only. Commit locally on branch `p2`, never push. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Judgment log: edit entries in place with no "Update:" notes; keep entry numbers stable; new entries from 35.

## Review Focus

1. A non-database error raised while binding a parameter (a lone surrogate in a farm name) is wrapped by SQLAlchemy in `StatementError`; clients must still get 422 `VALIDATION`, not 500. (Task 2)
2. Bound values that contain `:` or `%` (a farm named `50% :off`) are stored and returned verbatim on both backends. (Task 2)
3. A 503 log line must not contain SQL parameters (a farm name) or the password, though SQLAlchemy's own message holds both. (Task 2)
4. `seed.py` against a database that already has the tables, rows or both fails with a clear message, exit code 1, and changes nothing; with `DATABASE_URL` unset or `sqlite:` it refuses with no traceback. (Task 3)
5. `DATABASE_URL=` (set but empty) in the real environment beats a PostgreSQL URL in `.env` and means SQLite. (Task 1)

---

## File structure

- `config.py` (modify): keep URL parsing and targets; add `Settings`, `load_settings`, `postgres_connect_args`; drop `load_environment` and the import-time load.
- `db.py` (modify): engine factory, `Connection`/`Result` on SQLAlchemy, error classification.
- `catalogues.py`, `farms.py`, `plots.py` (modify): `:name` SQL and dict params only.
- `main.py` (modify): settings and engine in `lifespan`.
- `seeding.py` (create): `split_statements`, `seed_postgres`; `scripts/seed.py` (create): CLI.
- `sql/seed_data.sql` (create), `sql/postgres_schema.sql` (tables only), `sql/demo_data.sql` (delete), `seed_registry.sh` (modify).
- `tests/` (modify as listed per task), `README.md`, `.env.example`, `pyproject.toml`, `uv.lock`, `docs/judgment-log.md`.
- `/.claude/settings.json` (create), `/.gitignore` (modify): repo root.

---

### Task 1: Settings with pydantic-settings

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv`), `config.py`, `main.py`, `.env.example`, `tests/conftest.py`, `tests/pg_support.py`, `tests/test_config.py`, `tests/test_startup_config.py`, `tests/test_pg_infrastructure.py`
- Test: `tests/test_config.py`, `tests/test_startup_config.py`

**Interfaces:**
- Produces (`config.py`):
  - `class Settings(BaseSettings)`: field `DATABASE_URL: str | None = None`; `model_config` with `env_file=SERVICE_DIR / ".env"`, `extra="ignore"`, `hide_input_in_errors=True`. A `field_validator("DATABASE_URL")` calls `parse_database_url` so an invalid value raises `ConfigError` (not a pydantic error).
  - `load_settings(env_file: Path | None = None) -> Settings`: builds `Settings(_env_file=env_file or default)`; any `pydantic.ValidationError` becomes `ConfigError("Invalid settings")` raised `from None`.
  - `Settings.target` (property) `-> SqliteTarget | PostgresTarget`.
  - `postgres_connect_args(url: str) -> dict[str, str | int]`: libpq parameters from `conninfo_to_dict(url)` plus `connect_timeout=5` and `options` with ` -c lock_timeout=5000` appended to any existing options (this replaces `db.postgres_conninfo`).
- Removes: `load_environment`, the module-level `load_environment()` call, the `python-dotenv` dependency.
- Test support (`tests/pg_support.py`): `class TestEnv(BaseSettings)` reading `DATABASE_URL: str | None` and `TEST_DATABASE_URL: str | None`, raw and unvalidated, from the environment and the same `.env` (so a `TEST_DATABASE_URL` kept in `.env` keeps working, as today).

- [ ] **Step 1: Add the dependency.** Run `uv add pydantic-settings`, then edit its pin in `pyproject.toml` to the `~=` style of the others (resolved minor). `python-dotenv` stays until Step 4. Run `uv run pytest -q` and confirm the suite still passes unchanged.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`, replacing `test_load_environment_fills_missing_but_never_overrides`:
  - `test_settings_read_dot_env_when_no_real_variable(tmp_path, monkeypatch)`: `.env` with `DATABASE_URL=sqlite:///x.db`; `load_settings(env_file).target == SqliteTarget(SERVICE_DIR / "x.db")`.
  - `test_real_variable_beats_dot_env`: env `sqlite:///a.db`, `.env` has PostgreSQL URL; target is the SQLite one.
  - `test_empty_real_variable_beats_dot_env_and_means_default_sqlite`: `monkeypatch.setenv("DATABASE_URL", "")`, `.env` has a PostgreSQL URL; target is `SqliteTarget(DEFAULT_SQLITE_PATH)`.
  - `test_other_keys_in_dot_env_are_ignored`: `.env` with `TEST_DATABASE_URL=...` and `FOO=1` loads without error.
  - `test_invalid_value_raises_config_error_without_the_value`: `DATABASE_URL=postgresql://u:s3cret@h:99999/db`; `ConfigError` raised; `"s3cret"` not in `str(exc)` nor in `traceback.format_exception` output.
  - `test_connect_args_set_timeouts_and_append_to_existing_options`: `postgres_connect_args("postgresql://u@h/db?options=-csearch_path%3Dx")` has `connect_timeout == 5` and `options == "-csearch_path=x -c lock_timeout=5000"`.
  Port the existing `test_conninfo_sets_timeouts_and_appends_to_existing_options` assertions to the new function.
- [ ] **Step 3: Run them**: `uv run pytest tests/test_config.py -q`. Expected: the new tests FAIL (no `Settings`).
- [ ] **Step 4: Implement `Settings`, `load_settings`, `postgres_connect_args`** in `config.py` to the interfaces above. Keep every other function in `config.py` as is. Remove `from dotenv import load_dotenv`, then run `uv remove python-dotenv`.
- [ ] **Step 5: Wire startup.** In `main.py`'s `lifespan`: `settings = config.load_settings()`; `app.state.settings = settings`; `app.state.db_target = settings.target`. Remove `os.environ.get("DATABASE_URL")`. Update `tests/test_startup_config.py` for the new flow: keep every assertion about `app.state.db_target`, leaks and `.env` isolation; rewrite the `.env` tests to pass an env file through monkeypatching `config.Settings.model_config["env_file"]` (or a `load_settings` argument) instead of `load_dotenv`.
- [ ] **Step 6: Fix the test support.** Add `TestEnv` to `tests/pg_support.py`; in `tests/conftest.py` replace `import config as service_config`/`assert service_config` and `capture_developer_database_url(os.environ)` with `TestEnv().DATABASE_URL`, and read `TEST_DATABASE_URL` from `TestEnv()` in `pg_base_url`. Update `test_capture_ignores_empty_and_returns_value` and `test_session_start_capture_happens_before_fixtures` in `tests/test_pg_infrastructure.py` to the new capture path with the same assertions.
- [ ] **Step 7: Update `.env.example`** to say that unset or blank `DATABASE_URL` means SQLite and that the file is read by pydantic-settings; placeholders only.
- [ ] **Step 8: Run** `uv run pytest -q`. Expected: all pass (db.py is untouched; it still imports `postgres_conninfo`, so keep a one-line alias `postgres_conninfo` in `db.py` built on `postgres_connect_args` until Task 2).
- [ ] **Step 9: Commit** `git add -A services/registry-service && git commit -m "Read settings with pydantic-settings"`.

---

### Task 2: Data access on SQLAlchemy

**Files:**
- Modify: `db.py`, `catalogues.py`, `farms.py`, `plots.py`, `main.py`, `tests/conftest.py`, `tests/test_db_adapter.py`, `tests/test_db_postgres_adapter.py`, `tests/test_postgres_failures.py`, `tests/test_real_sqlite_path.py`, `tests/test_farms.py` (new cases)
- Test: the same files

**Interfaces:**
- Produces (`db.py`):
  - `DatabaseUnavailable`, `IntegrityViolation` unchanged.
  - `create_engine_for(target: SqliteTarget | PostgresTarget) -> sqlalchemy.Engine`: `poolclass=NullPool`; SQLite URL `sqlite+pysqlite:///file:<posix path>?mode=rw&uri=true`, `connect_args={"check_same_thread": False}`, a `connect` event that runs `PRAGMA foreign_keys = ON`; PostgreSQL `create_engine("postgresql+psycopg://", connect_args=config.postgres_connect_args(target.url))`. It does not connect.
  - `class Connection`: `execute(sql: str, params: Mapping[str, Any] | None = None) -> Result`; `commit()`, `rollback()`, `close()`; property `raw` returning the driver connection (`sa_conn.connection.driver_connection`), kept for the fault-injection tests.
  - `class Result`: `rowcount: int`; `fetchone() -> Mapping | None` and `fetchall() -> list[Mapping]` returning row mappings that `dict(row)` accepts; fetch errors are translated like execute errors.
  - `open_connection(engine: Engine) -> Connection`: any failure opening raises `DatabaseUnavailable` (entry 26) after one WARNING.
  - `get_db(request: Request) -> Iterator[Connection]`: uses `request.app.state.engine`.
  - `classify_error(exc: Exception, invalidated: bool) -> Literal["unavailable", "integrity", "other"]` (replaces `classify_postgres_error` and the SQLite classifier): `sqlalchemy.exc.IntegrityError` is integrity; the driver error `exc.orig` with `sqlite_errorname` in `{"SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_CANTOPEN"}`, or a `sqlstate` in `{"57P01","57P02","57P03","53300","55P03","40001","40P01"}` or starting with `"08"`, is unavailable; an `OperationalError` with `invalidated` true is unavailable; everything else is other.
- `main.py` `lifespan`: after settings, `app.state.engine = db.create_engine_for(settings.target)`; after `yield`, `app.state.engine.dispose()`.
- Unwrap rule: SQLAlchemy wraps non-database errors raised during execute in `StatementError`. For "other", re-raise the original (`exc.orig`) so `UnicodeEncodeError` and driver errors keep their types and reach the same handlers.
- Logging: `_log_unavailable(exc)` formats the driver error (`exc.orig`) only, with the entry 27 rules (class name, code, text only for `sqlite3.Error` and `psycopg.OperationalError`), never `str(exc)` of the SQLAlchemy exception.
- Router change: every `?` becomes `:name`; params are dicts (`{"id": crop_id}`); `plots.py` builds its INSERT placeholders as `", ".join(f":{c}" for c in PLOT_COLUMNS_LIST)` and its UPDATE with `name = :name` style, params keyed by column name (`plot_id` as `id`); `check_references` passes `{"id": value}`.

- [ ] **Step 1: Write failing tests (SQLite, no server)** in `tests/test_db_adapter.py`, using `db.create_engine_for(SqliteTarget(path))` and `db.open_connection(engine)` in the fixture on a temp copy of `registry.db`. Keep every existing assertion (integrity rolls back then raises; busy database raises `DatabaseUnavailable` and logs once; missing file raises unavailable; integrity writes no log; other errors pass through unchanged; lone surrogate passes through; fetch errors translated; rows come back as dicts). Replace `test_percent_in_sql_is_rejected` with `test_literal_percent_in_sql_is_accepted`: `conn.execute("SELECT '100%' AS v").fetchone()["v"] == "100%"`. Add `test_colon_in_a_bound_value_is_kept`: insert a farm named `a:b`, read it back equal. Add `test_lone_surrogate_reaches_the_caller_as_unicode_encode_error`. Replace `FailingCursor` and `sqlite_error` helpers with a stub that raises through `Result` (a `StatementError`-wrapped `sqlite3.OperationalError` with `sqlite_errorname`), keeping the assert-once-logged checks.
- [ ] **Step 2: Write failing tests (PostgreSQL, fake errors, no server)** in `tests/test_db_postgres_adapter.py`: port `test_classification_table` to `classify_error` (same table of SQLSTATEs, wrapped in `sqlalchemy.exc.OperationalError`/`IntegrityError` with `orig`), `test_integrity_error_rolls_back_then_raises`, `test_failed_rollback_becomes_unavailable`, `test_commit_errors_are_translated`, the three log-secrecy tests (`password`, malformed percent escape, non-operational connect error text withheld), and `test_operational_connect_error_keeps_the_cause`. Drop `test_translate_placeholders`. Add `test_log_never_contains_sql_parameters`: a failing statement with a parameter value `SECRET-FARM-NAME` logs a line without it.
- [ ] **Step 3: Run** `uv run pytest tests/test_db_adapter.py tests/test_db_postgres_adapter.py -q`. Expected: FAIL (old API).
- [ ] **Step 4: Rewrite `db.py`** to the interfaces above. Remove the `%` guard, `translate_placeholders`, `SqliteConnection`/`PostgresConnection`, `connect`, `connect_postgres`, `connect_target` and the Task 1 alias. Keep `DB_PATH` and the logger name `registry.db`.
- [ ] **Step 5: Convert the routers** (`catalogues.py`, `farms.py`, `plots.py`) as described. Do not change any route, status, detail text or response field.
- [ ] **Step 6: Rewrite the fixtures** in `tests/conftest.py`: `use_database(path)` creates one engine per fixture (`create_engine_for(SqliteTarget(path))`), overrides `get_db` with `open_connection`, and disposes at teardown; `TestDatabase.connect` returns `open_connection(create_engine_for(...))` for both backends; `locked_client` keeps its raw `sqlite3` lock and still sets `PRAGMA busy_timeout = 100` through `conn.execute`; the `raw`-based fault tests in `tests/test_postgres_failures.py` keep working through `Connection.raw` (replace `db.connect_postgres(url)` with `db.open_connection(db.create_engine_for(PostgresTarget(url)))`; `conn.raw.info.backend_pid` and `conn.raw.fileno()` stay). Fix `tests/test_real_sqlite_path.py` the same way. Fault injection and setup in tests may keep using raw `sqlite3`/`psycopg`.
- [ ] **Step 7: Add endpoint tests** in `tests/test_farms.py` (parametrized on `database`, so both backends): `test_farm_name_with_colon_and_percent_roundtrips` (`50% :off` via POST then GET returns the same name, 201 then 200); `test_lone_surrogate_name_returns_422_validation` (problem+json, code `VALIDATION`, not 500).
- [ ] **Step 8: Run** `uv run pytest -q`. Expected: all pass on SQLite; PostgreSQL tests skipped (no `TEST_DATABASE_URL`).
- [ ] **Step 9: Commit** `git commit -am "Run data access on SQLAlchemy Core"` (add any new files).

---

### Task 3: Shared seed data and the seed command

**Files:**
- Create: `sql/seed_data.sql`, `seeding.py`, `scripts/seed.py`, `tests/test_seed.py`
- Modify: `sql/postgres_schema.sql`, `seed_registry.sh`, `tests/conftest.py`, `tests/test_pg_infrastructure.py`
- Delete: `sql/demo_data.sql`

**Interfaces:**
- Produces (`seeding.py`):
  - `split_statements(script: str) -> list[str]`: drops `--` comment lines, splits on `;` at end of line, strips, ignores empty parts.
  - `seed_postgres(engine: Engine) -> None`: in one `engine.begin()` transaction runs each statement of `sql/postgres_schema.sql` then `sql/seed_data.sql` through `text()`. Errors propagate; the transaction rolls back.
  - `class SeedError(Exception)`, raised by `scripts/seed.py` logic for refusal cases.
- `scripts/seed.py`: `main() -> int`; loads settings via `config.load_settings()`, refuses a `SqliteTarget` ("seed.py loads PostgreSQL only; use seed_registry.sh for SQLite"), calls `seed_postgres`, prints `Created 5 tables and loaded 15 rows (2 crops, 3 soils, 4 emitters, 2 farms, 4 plots).` and returns 0; on any database error prints a short message without the URL or driver text and returns 1. Run as `uv run python scripts/seed.py`; it must add the service folder to `sys.path` itself.
- `sql/seed_data.sql`: the 15 `INSERT`s in the order crops, soils, emitters, farms, plots, with the exact values currently in `seed_registry.sh` and `postgres_schema.sql`/`demo_data.sql`; no `:` outside string values that need none; header comment says it is shared by both backends.

- [ ] **Step 1: Write failing tests** in `tests/test_seed.py`:
  - `test_split_statements_drops_comments_and_blank_parts`.
  - `test_seed_data_file_has_15_inserts_in_dependency_order` (counts by table: 2/3/4/2/4, plots last).
  - `test_sqlite_rebuild_matches_the_baseline_rows(tmp_path)`: run `bash seed_registry.sh <tmp>/registry.db` from a different working directory (`cwd=tmp_path`), dump rows per table as in Global Constraints, compare with the same dump of the current `registry.db`, and compare `.schema` output too. (If `sqlite3` is missing, skip.)
  - PostgreSQL (skip without `TEST_DATABASE_URL`; use a fresh schema through `pg_support`): `test_seed_postgres_loads_15_rows_by_table`, `test_second_seed_fails_and_changes_nothing` (counts before and after equal; `DuplicateTable` surfaces as a `sqlalchemy.exc.ProgrammingError`), `test_seed_into_tables_that_exist_but_are_empty_fails_and_adds_no_rows`.
  - `test_cli_refuses_sqlite_and_unset_without_traceback`: run `scripts/seed.py` as a subprocess with `DATABASE_URL=sqlite:///x.db` and with it unset in a clean environment (no `.env` effect: pass `cwd` and an env without the variable; the service `.env` may exist, so set `DATABASE_URL=` empty explicitly); exit code 1, the refusal text in output, no `Traceback`.
  - `test_cli_failure_message_has_no_url` (PostgreSQL URL with a wrong password and a marker password: output lacks the marker).
- [ ] **Step 2: Run** `uv run pytest tests/test_seed.py -q`. Expected: FAIL.
- [ ] **Step 3: Create `sql/seed_data.sql`** by moving the rows; trim `sql/postgres_schema.sql` to tables only and update its header comment; delete `sql/demo_data.sql`.
- [ ] **Step 4: Change `seed_registry.sh`**: keep the SQLite `CREATE TABLE` block and `PRAGMA foreign_keys = ON`; replace the inline `INSERT`s with `.read "$here/sql/seed_data.sql"` inside the `sqlite3` heredoc, where `here` is the script's own directory (`$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`). Keep the final `echo` lines.
- [ ] **Step 5: Implement `seeding.py` and `scripts/seed.py`** to the interfaces.
- [ ] **Step 6: Point the fixtures at the seed function.** In `tests/conftest.py`'s `pg_schema` fixture, build `create_engine_for(PostgresTarget(with_options(base, "-csearch_path=<schema>")))`, call `seeding.seed_postgres(engine)`, dispose it; replace the `postgres_schema.sql`/`demo_data.sql` loop. In `tests/test_pg_infrastructure.py`: `test_schema_script_fails_on_second_run` now calls `seed_postgres` twice and expects the SQLAlchemy error; keep `test_pg_schema_contains_demo_data` (2 farms, 4 plots) and the drift test `test_catalogue_and_demo_rows_match_sqlite_seed` unchanged in assertions.
- [ ] **Step 7: Run** `uv run pytest -q`. Expected: pass; then rebuild the local file with `bash seed_registry.sh` and re-run `uv run pytest -q` to confirm tests still pass on the rebuilt `registry.db`; check the dump hash equals `5fca1040...` (`sha256sum` of the dump built exactly as in Global Constraints).
- [ ] **Step 8: Commit** `git add -A services/registry-service && git commit -m "Share the seed rows and add the seed command"`.

---

### Task 4: PostgreSQL run and p95 measurement

**Files:**
- Modify: `README.md` (Performance section only, after the measurement)
- No code changes expected; fix findings in the files of Tasks 1-3.

**Interfaces:** consumes `TEST_DATABASE_URL`, `scripts/seed.py`, `scripts/measure_p95.py`.

- [ ] **Step 1: Get a throwaway PostgreSQL.** Reuse the P1 container (`registry-pg-test`, 127.0.0.1:55432, via `docker.exe` in this WSL) or start a new one; the user allowed this on 2026-11-11. Use two databases: one for `TEST_DATABASE_URL`, one for the p95 run. Never put these URLs in a committed file.
- [ ] **Step 2: Run the full suite on PostgreSQL**: `TEST_DATABASE_URL=... uv run pytest -q`. Expected: everything passes, nothing skipped except tests that need `sqlite3`-only conditions. Fix any failure at its cause, never by weakening an assertion; add a test for any real bug found.
- [ ] **Step 3: Seed and measure.** `DATABASE_URL=<p95 db> uv run python scripts/seed.py`, then start `DATABASE_URL=<p95 db> uv run uvicorn main:app --host 127.0.0.1 --port 8000` and run `uv run python scripts/measure_p95.py`. Expected: exit 0, `Not 200: 0`, overall p95 <= 100 ms.
- [ ] **Step 4: Decide on a pool.** If p95 is over 100 ms, stop and report to the user (a pool is a separate decision). Otherwise record the measured numbers and conditions in the README Performance section, replacing the SQLite-only 8.8 ms figure (say which backend each figure is from, and keep the SQLite figure labeled as SQLite).
- [ ] **Step 5: Commit** `git commit -am "Record the PostgreSQL p95 measurement"`.

---

### Task 5: Repo settings file and .gitignore

**Files:**
- Create: `/.claude/settings.json` (repo root `/home/asaf/ArgoPilot/.claude/settings.json`)
- Modify: `/.gitignore`

- [ ] **Step 1: Check what the root `.claude/` holds**: `ls -a /home/asaf/ArgoPilot/.claude /home/asaf/ArgoPilot/.claude/skills` and `git ls-files .claude`; note the exact skill-creator folder path.
- [ ] **Step 2: Create `settings.json`** with `{"permissions": {"deny": ["Read(**/.env)"]}}` (pretty-printed).
- [ ] **Step 3: Narrow `.gitignore`**: replace `/.claude/` with `/.claude/skills/skill-creator/`, keep `/skills-lock.json`.
- [ ] **Step 4: Verify**: `git check-ignore -v .claude/settings.json` prints nothing (not ignored) and exits 1; `git check-ignore -v .claude/skills/skill-creator` is ignored; `git status --short` shows `.claude/settings.json` as new and nothing else from `.claude/` unexpectedly.
- [ ] **Step 5: Commit** `git add .claude/settings.json .gitignore && git commit -m "Commit the Claude settings that deny reading .env"`.

---

### Task 6: README and judgment log

**Files:**
- Modify: `README.md`, `docs/judgment-log.md`

- [ ] **Step 1: README.** Rewrite Setup, Database, "PostgreSQL schema" and the seed paragraph: the one command is `uv run python scripts/seed.py` (PostgreSQL only, needs `DATABASE_URL`, loads sample data, second run fails and changes nothing); keep the PostgreSQL prerequisites list; drop the `psql` instructions and the "Never load demo data in production" paragraph; say `.env` is read by pydantic-settings and a real variable wins; add the position paragraph: `DATABASE_URL` is optional, the registry fails loudly on an invalid value, and the "missing required variable" rule is demonstrated in the new services; mention `seed_registry.sh` now reads `sql/seed_data.sql`.
- [ ] **Step 2: Judgment log edits in place** (no "Update:" notes, numbers stable): entries 17 (python-dotenv becomes pydantic-settings), 18 (SQLAlchemy Core with text SQL), 19 (a literal `%` is safe because `text()` escapes it; a literal `:` must be `\:`), 22 (seed command, all 15 rows, nothing on startup), 23 and 24 (mechanism now `NullPool` and `connect_args`), 26, 27, 28, 31, 32 only where they name `python-dotenv`, `psycopg` internals, `load_environment` or the old SQL files; re-read all 34 entries and fix anything else that became inaccurate (entries 1 and 11 must name the new classifier and `IntegrityError`).
- [ ] **Step 3: New entries 35+**: NullPool instead of SQLAlchemy's default pool; engine built with the `postgresql+psycopg` driver and libpq-style connect args; settings errors hide input and re-raise a fixed message; `DATABASE_URL` optional with the README position; `TEST_DATABASE_URL` read by a test-only settings class; one shared `seed_data.sql`; `seed.py` refuses SQLite; a second seed run fails and rolls back; PostgreSQL p95 result (from Task 4). Same Suggested/Decided/Why shape as the existing entries.
- [ ] **Step 4: Verify** `uv run pytest -q` passes; `grep -n "Update:" docs/judgment-log.md` finds nothing new; the log has entries 1-34 plus the new ones with no duplicate numbers.
- [ ] **Step 5: Commit** `git commit -am "Document the SQLAlchemy change in the README and judgment log"`.

---

## Self-review

- Spec coverage: 5.1 (Task 1), 5.2 (Task 2), 5.3 (Task 3), 5.4 (Tasks 1-3), 5.5 (Task 4), 5.6 (Tasks 1, 5), 5.7 (Task 6). The new-service README sentence and the SQLite-only 8.8 ms note are in Tasks 4 and 6.
- Plan calls beyond the spec: `TEST_DATABASE_URL` and the developer `DATABASE_URL` capture move to a test-only `TestEnv`, because python-dotenv no longer copies `.env` into the environment; `seeding.py` holds the importable seed function because `scripts/` is not on the test import path; `Connection.raw` stays for the fault-injection tests.
