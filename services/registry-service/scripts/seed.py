"""Create the tables and load the sample data into an empty PostgreSQL database.

Run from services/registry-service:

    uv run python scripts/seed.py

DATABASE_URL (environment or .env) must point at an empty PostgreSQL database. A second run
fails and changes nothing. The messages never show the URL, the password or driver text.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
from seeding import SeedError, require_postgres, seed_postgres  # noqa: E402

TABLE_EXISTS_SQLSTATE = "42P07"


def main() -> int:
    try:
        target = require_postgres(config.load_settings().target)
    except (config.ConfigError, SeedError) as exc:
        print(f"Error: {exc}")
        return 1

    engine = db.create_engine_for(target)
    try:
        seed_postgres(engine)
    except Exception as exc:
        # Nothing from the exception is printed: its text can hold the host or the user.
        driver = db.driver_error(exc)
        if getattr(driver, "sqlstate", None) == TABLE_EXISTS_SQLSTATE:
            print("The tables already exist. Seed an empty database. Nothing was changed.")
        elif isinstance(driver, psycopg.OperationalError):
            print("The database is unavailable or refused the connection. Nothing was changed.")
        else:
            print("Seeding failed. Nothing was changed.")
        return 1
    finally:
        engine.dispose()

    print("Created 5 tables and loaded 15 rows (2 crops, 3 soils, 4 emitters, 2 farms, 4 plots).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
