# Registry service

The registry service manages farms and plots, and offers read-only catalogues of crops, soils and emitters. It is built with FastAPI. It runs on SQLite (local use and tests) or on PostgreSQL (production).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and the `sqlite3` command. Run these from this folder:

```bash
uv sync
bash seed_registry.sh
```

The second command creates `registry.db`. Running it again gives a clean file.

## Database

`DATABASE_URL` chooses the database:

- `postgresql://USER:PASSWORD@HOST:5432/DBNAME` (or `postgres://`) selects PostgreSQL.
- `sqlite:///path` selects SQLite. A relative path is resolved against the service directory, not the working directory.
- Unset or empty means the local `registry.db`.

The service loads `.env` from the service directory. A real environment variable wins over the file. The URL is checked at startup, and a bad one stops the service with a message that does not show the URL.

Percent-encode special characters (`@ / : ? # %`) in a user name or password. An unencoded `@` after the host part is rejected at startup.

Farm and plot names are limited to 200 characters (after surrounding spaces are stripped). A longer name returns 422.

Never put a real `DATABASE_URL` in `.env.example`. That file is committed and must hold placeholders only. The real `.env` stays out of git.

### PostgreSQL schema

PostgreSQL prerequisites:

- PostgreSQL 12 or later. Older servers return floats with 15 digits, so the exact float round trip fails.
- A UTF8 database. With LATIN1, non-Latin names get a 422 "invalid characters". With SQL_ASCII, values come back as bytes.
- The service role must own the tables or be granted access. The script has no GRANTs, so run it as the service role, or grant SELECT, INSERT, UPDATE and DELETE on the five tables. Otherwise every request fails with a 500.
- Behind PgBouncer, the `options` startup parameter is rejected unless the pooler is set to ignore it. The service sets `options` for `lock_timeout`.

The service never creates tables. Run the schema script by hand. `psql` does not read `DATABASE_URL` or `.env`, so export the variable and pass it as the connection. An unset variable then fails loudly:

```bash
psql "${DATABASE_URL:?DATABASE_URL is not set}" --single-transaction -v ON_ERROR_STOP=1 -f sql/postgres_schema.sql
```

The `PG*` environment variables work too; then leave out the URL argument. A URL that contains a password is visible in the process list on a shared host, so use `PGPASSWORD` or `~/.pgpass` there.

It creates the tables and loads the catalogues (crops, soils, emitters). That is all production gets. A second run fails, and a failure leaves nothing behind. `sql/demo_data.sql` holds demo farms and plots for local use and tests. Never load it in production.

## Run

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

`GET /health` returns `{"status": "ok"}`. The API is under `/v1`.

## Tests

```bash
uv run pytest
```

By default the tests use SQLite only, whatever `DATABASE_URL` says. They work on a copy of the database, so `registry.db` is not changed.

### PostgreSQL tests

Set `TEST_DATABASE_URL` to a throwaway PostgreSQL database, whose user may create schemas:

```bash
TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/TEST_DBNAME uv run pytest
```

Without it, the PostgreSQL tests are skipped. Each test creates its own schema `test_<hex>` and drops it afterwards. The PostgreSQL tests refuse to run if `TEST_DATABASE_URL` points at the same database as `DATABASE_URL`, or is not a `postgresql://` or `postgres://` URL with a host.

## Errors

Every error is `application/problem+json`, with a `code` of `VALIDATION`, `NOT_FOUND`, `CONFLICT` or `UNAVAILABLE`.

## Performance

Read routes measured at p95 8.8 ms, against a target of 100 ms or less. Conditions: 1200 requests at 10 requests per second, on a local server with the seed data.

To repeat it, start the server, then run:

```bash
uv run python scripts/measure_p95.py
```

## Decisions

See [docs/judgment-log.md](docs/judgment-log.md).
