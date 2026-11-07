# Registry service

The registry service manages farms and plots, and offers read-only catalogues of crops, soils and emitters. It is built with FastAPI and SQLite.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and the `sqlite3` command. Run these from this folder:

```bash
uv sync
bash seed_registry.sh
```

The second command creates `registry.db`. Running it again gives a clean file.

## Run

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

`GET /health` returns `{"status": "ok"}`. The API is under `/v1`.

## Tests

```bash
uv run pytest
```

The tests work on a copy of the database, so `registry.db` is not changed.

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
