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

Do not enable DEBUG logging for the `sqlalchemy.engine` logger in production, because it logs result rows.

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

Target: p95 of 100 ms or less for the read routes.

**PostgreSQL 17**, measured with the seed data loaded by `scripts/seed.py`: overall p95 **34.2 ms**. Per route:

| Route | p95 |
|---|---|
| `/v1/farms` | 31.3 ms |
| `/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001` | 38.2 ms |
| `/v1/plots` | 40.0 ms |
| `/v1/plots/c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002` | 35.7 ms |
| `/v1/crops` | 31.2 ms |
| `/v1/crops/tomato` | 33.8 ms |
| `/v1/soils` | 34.2 ms |
| `/v1/soils/loam` | 29.0 ms |
| `/v1/emitters` | 33.8 ms |
| `/v1/emitters/dripnet-pc-1.0` | 34.2 ms |

Conditions: WSL2 on one machine. PostgreSQL 17.11 in a local container, reached through Docker at 127.0.0.1. One uvicorn process, no connection pool. 1200 requests at 10 requests per second over 120 seconds. 0 responses other than 200.

The PostgreSQL figure is higher than the SQLite one, probably because each request opens a new database connection (judgment log, entry 23). This was not measured separately. The figure is well under the 100 ms target, so no pool was added.

**SQLite**, measured in task P1 (not repeated for this change): read routes at p95 8.8 ms. Conditions: 1200 requests at 10 requests per second, on a local server with the seed data.

To repeat the PostgreSQL measurement, seed an empty database, start the server against it, then run the script:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME uv run python scripts/seed.py
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME uv run uvicorn main:app --host 127.0.0.1 --port 8000
uv run python scripts/measure_p95.py
```

## Decisions

See [docs/judgment-log.md](docs/judgment-log.md).
