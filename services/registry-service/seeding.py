"""Create the tables and load the 15 sample rows into an empty PostgreSQL database."""

import re
from pathlib import Path

import sqlalchemy as sa

from config import PostgresTarget, SqliteTarget

SQL_DIR = Path(__file__).resolve().parent / "sql"
SCHEMA_FILE = SQL_DIR / "postgres_schema.sql"
SEED_DATA_FILE = SQL_DIR / "seed_data.sql"


class SeedError(Exception):
    """The seed command cannot run against this target. The message is safe to print."""


def split_statements(script: str) -> list[str]:
    """Split a SQL file into statements: comment lines dropped, split at a `;` that ends a line.

    A `;` inside a string literal that is also the last character on its line would be split
    wrongly. The two seed files have none.
    """
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    parts = re.split(r";[ \t]*(?:\n|$)", "\n".join(lines))
    return [part.strip() for part in parts if part.strip()]


def require_postgres(target: SqliteTarget | PostgresTarget) -> PostgresTarget:
    if not isinstance(target, PostgresTarget):
        raise SeedError(
            "seed.py loads PostgreSQL only. Set DATABASE_URL to a postgresql:// URL, "
            "or use seed_registry.sh for SQLite."
        )
    return target


def seed_postgres(engine: sa.Engine) -> None:
    """Create the five tables and load the sample rows in ONE transaction.

    Errors propagate. If any statement fails, for example because a table already exists, the
    transaction is rolled back and the database is left as it was.
    """
    statements = split_statements(SCHEMA_FILE.read_text()) + split_statements(SEED_DATA_FILE.read_text())
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(sa.text(statement))
