# Registry service on SQLAlchemy, pydantic-settings and a seed command: design

Status: draft for review. Branch: `p2`. Date: 2026-11-15.
Builds on `2026-11-11-registry-postgres-design.md`. Where the two disagree, this one wins.

## 1. Intent

Task P2 asks the registry part of AgroPilot to meet these requirements:

- FR-2.1 / NFR-2.1: SQLite on a developer machine, PostgreSQL in production, switched by configuration only.
- FR-2.2: one documented command creates the tables in an empty PostgreSQL database and loads the same 15 seed rows as `seed_registry.sh` (2 crops, 3 soils, 4 emitters, 2 farms, 4 plots).
- NFR-2.2: GET list and GET by id, p95 <= 100 ms at 10 requests per second, on PostgreSQL.
- All data access goes through SQLAlchemy.
- Settings are read with pydantic-settings in one `config.py`; a missing required variable stops startup with a clear error; `.env.example` is committed.
- A `.claude/settings.json` at the repo root denies `Read(**/.env)` and is committed.

The service already runs on both backends through raw `sqlite3` and `psycopg`. This change swaps the data layer and the settings layer, and adds the seed command. Behavior seen by clients must not change.

## 2. Goals, non-goals, anti-goals

Goals
- Every endpoint answers exactly as today: status codes, problem+json `code`s, `Retry-After` on 503, the 503 vs 500 split.
- All data access (the app, the seed command) goes through SQLAlchemy Core.
- One seed command; the rows live in one SQL file shared by both backends.
- The existing tests keep their meaning on both backends.

Non-goals
- No ORM, no models, no query builder. The SQL stays as text (`sqlalchemy.text`).
- No Alembic or migrations. No schema creation on app startup.
- No connection pool unless the PostgreSQL p95 measurement is over 100 ms.
- No new endpoints, fields or response changes.
- `seed.py` does not seed SQLite (`seed_registry.sh` does).
- Deny rule limits: `Read(**/.env)` blocks the Read tool, not `cat .env` in a shell. We do not try to cover that here.

Anti-goals (a failure even if the tests pass)
- A password or URL in a log line, an error message or a `repr`.
- A hidden connection pool that quietly changes entry 23 (one connection per request).
- The SQLite and PostgreSQL seed rows able to drift apart.

## 3. Constraints

- Python 3.12, FastAPI, uv. `psycopg` stays as the PostgreSQL driver.
- SQLAlchemy picks `psycopg2` for a bare `postgresql://` URL. The engine URL must therefore be built as `postgresql+psycopg://...` from the validated target. The user-facing `DATABASE_URL` keeps accepting `postgresql://` and `postgres://`.
- Behavior rules kept: rollback before raising `IntegrityViolation`; connect timeout 5 s and lock timeout 5 s on PostgreSQL; one connection per request; `ConfigError` messages never contain the URL or password; the same-database safety check in tests.
- A literal `:` in SQL text is read as a parameter by `text()` and must be written `\:`. A literal `%` is safe (checked 2026-11-15: `text()` doubles it for psycopg and leaves it alone for SQLite).

## 4. Approaches considered

Data access
- A. Keep the `Connection`/`Result` wrapper in `db.py`, swap its inside to SQLAlchemy. Routers still call `conn.execute(sql, params)` and read rows by name; only the SQL strings and params change to `:name` and dicts. Error handling stays in `db.py`. Small, keeps entry 1 true.
- B. Drop the wrapper; routers use a SQLAlchemy connection directly and errors are translated in a context manager or app handler. More idiomatic, but every router changes and the parity risk is higher for no behavior gain.
- C. Keep `?` and convert it to `:name` inside the wrapper. Fewest router edits, but a hidden translation layer and it contradicts the `:name` decision.

Chosen: A (user's decision, 2026-11-15).

Seed command
- 1. `scripts/seed.py`, run with `uv run python scripts/seed.py`. Chosen. Needs no `psql`, and keeps all data access in SQLAlchemy.
- 2. Keep `psql -f` on the SQL files. Smallest change, but production needs a `psql` client and the documented command becomes two files.

## 5. Design

### 5.1 `config.py` (pydantic-settings)

- One `Settings(BaseSettings)` class replaces `load_environment()` and `python-dotenv`.
- One optional field, `DATABASE_URL: str | None`. Unset or blank means local SQLite (`registry.db`). `TEST_DATABASE_URL` and any other key in `.env` are ignored (`extra="ignore"`).
- The `.env` file is found next to `config.py`, not in the current directory. A real environment variable beats `.env` (the pydantic-settings default order).
- Validation stays as is: `parse_database_url` and the libpq-is-the-authority check keep deciding what a URL means. An invalid value stops startup with a `ConfigError` whose message never contains the URL. pydantic's own `ValidationError` text can echo the input, so input echo is turned off and the error is re-raised as the fixed `ConfigError` message.
- `PostgresTarget` and `SqliteTarget` keep their redacted `repr`/`str`.
- No variable is required. The README states that the "missing required variable" rule is demonstrated in the new services, and that the registry fails loudly on an invalid value instead.
- `.env.example` stays committed and is updated to match.

### 5.2 `db.py` (SQLAlchemy, approach A)

- One `Engine` is created at startup in `lifespan` from the validated target and stored on `app.state`; it is disposed at shutdown.
- `NullPool` on both backends: one connection per request, opened and closed in `get_db`, as today.
- SQLite: the file must exist (no silent create), `PRAGMA foreign_keys = ON` on every connection, a connection may cross threads. Today's timeouts and error codes are unchanged.
- PostgreSQL: `connect_timeout=5` and `lock_timeout=5000` passed as connect arguments.
- The wrapper keeps `execute`, `commit`, `rollback`, `close` and the result methods the routers use. Params are dicts and SQL uses `:name`.
- Error translation stays in `db.py` and reads the driver error from SQLAlchemy's wrapper (`exc.orig`, `connection_invalidated`). The unavailable SQLite codes, the PostgreSQL SQLSTATEs (class 08 and the listed ones) and the "integrity" class are the same sets as today. Every failure while opening a connection returns 503. Anything else is still a 500.
- Logging stays on the 503 path only and never formats the URL, `repr(exc)` or SQL parameters.
- The literal-`%` guard is removed (nothing to protect).

### 5.3 Seed data and the seed command

- `sql/seed_data.sql`: the 15 `INSERT`s in dependency order (crops, soils, emitters, farms, plots), plain SQL that runs unchanged on both backends. It replaces the rows now in `postgres_schema.sql` (catalogues) and `demo_data.sql`; `demo_data.sql` is removed.
- `sql/postgres_schema.sql`: tables only.
- `scripts/seed.py`: reads `DATABASE_URL` through `config.py`, refuses a SQLite or unset target with a clear message, then applies `postgres_schema.sql` and `seed_data.sql` through SQLAlchemy in one transaction. A second run fails on the existing tables and rolls back, leaving nothing changed. Its seed function is importable.
- `seed_registry.sh`: keeps its own SQLite table definitions and now loads rows from `sql/seed_data.sql` (path relative to the script, not the current directory). The inline row copy is deleted.
- Must hold: rebuilding `registry.db` gives exactly the same rows as before (baseline dump captured 2026-11-15: 5 tables, 15 rows, sha256 `5fca1040563d1f47fddc664b110a6ab3ff893164c61720bd8e7bd46b046f3797` over the ordered per-table dump), with the same table definitions. No test reads the script's text; tests copy `registry.db`, so they see no change.
- The README documents the one command and says it loads sample data.

### 5.4 Tests

- Endpoint, parity, parallel and failure tests keep their assertions on both backends.
- The adapter-level tests that poke the old `sqlite3`/`psycopg` internals (`test_db_adapter.py`, `test_db_postgres_adapter.py`, `test_postgres_failures.py`, `test_pg_infrastructure.py`) are rewritten against the new internals with the same behavior assertions (same codes, same 503/500 split, rollback before integrity error, timeouts, no secret in logs).
- The PostgreSQL schema fixture calls the same seed function as the script.
- The drift test stays: PostgreSQL rows after seeding equal the SQLite `registry.db` rows. New tests: `seed.py` gives 15 rows (2/3/4/2/4); second run fails and leaves the database unchanged; `seed.py` refuses `sqlite:`; a `%` query works on both backends; a missing `.env` or a real variable overriding `.env`; an invalid `DATABASE_URL` stops startup without leaking it.

### 5.5 Performance

- `scripts/measure_p95.py` is run against PostgreSQL seeded with `seed.py`, at 10 requests per second. The 8.8 ms figure in the README was measured on SQLite only; the PostgreSQL measurement is still to be done and its result replaces it.
- If p95 on PostgreSQL is over 100 ms, add a pool as a separate, logged decision. Otherwise no pool.

### 5.6 Repo files

- `.claude/settings.json` at the repo root: deny `Read(**/.env)`. Committed.
- Root `.gitignore`: replace the `/.claude/` rule with rules that ignore only the skill-creator folder (exact path confirmed in the plan) and `/skills-lock.json`.
- `pyproject.toml` / `uv.lock`: add `sqlalchemy` and `pydantic-settings`, remove `python-dotenv`. `psycopg[binary]` stays.

### 5.7 Judgment log

- Entry 18 (thin adapter, no ORM): edited in place to describe SQLAlchemy Core with text SQL.
- Entry 22 (schema script by hand): edited in place to describe `scripts/seed.py`, all 15 rows, nothing on startup.
- Entry 19 (reject literal `%`): rewritten in place, so entry numbers stay stable: a literal `%` is safe because `text()` escapes it, and a literal `:` must be `\:`.
- Entry 17 and any other entry (23, 24, 26, 27, 28, 31, 32) that names `python-dotenv`, `sqlite3`/`psycopg` internals or `load_environment` are re-read and corrected in place, with no "Update:" notes.
- New entries from 35 on: NullPool in place of SQLAlchemy's default pool; engine URL built as `postgresql+psycopg://`; input echo off in settings errors; `DATABASE_URL` stays optional and the README states the "required variable" position; shared `seed_data.sql` as the single source; `seed.py` refuses SQLite; second run fails and rolls back; PostgreSQL p95 still to measure.

## 6. Left to the builder

- Exact SQLAlchemy engine options for SQLite transaction handling, so rollback and autobegin behave as today.
- How `get_db` and the test overrides pass the engine.
- Wording of error and README text, within the rules above.

## 7. Open points

None for the user. Calls made by the assistant: entry 19 rewritten rather than deleted (keeps numbering); adapter-level tests rewritten against new internals; `seed.py` seeds PostgreSQL only.
