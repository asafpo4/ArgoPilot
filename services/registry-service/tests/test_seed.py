"""The shared seed data, seed_registry.sh and the PostgreSQL seed command."""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

import db
from config import PostgresTarget, SqliteTarget, parse_database_url
from pg_support import with_options
from seeding import SQL_DIR, SeedError, require_postgres, seed_postgres, split_statements

SERVICE_DIR = Path(__file__).resolve().parent.parent
TABLES = ["crops", "soils", "emitters", "farms", "plots"]  # In dependency order.
EXPECTED_COUNTS = {"crops": 2, "soils": 3, "emitters": 4, "farms": 2, "plots": 4}

# Captured on 2026-11-15 from the registry.db that seed_registry.sh built before the rows moved
# into sql/seed_data.sql. Rows: `SELECT * FROM <t> ORDER BY id` per table in TABLES order, each
# preceded by a "-- <t>" line. Schema: the output of `.schema`.
BASELINE_ROWS_SHA256 = "5fca1040563d1f47fddc664b110a6ab3ff893164c61720bd8e7bd46b046f3797"
BASELINE_SCHEMA_SHA256 = "b1029b6385bfd75548d44a337323d8e849b6fa50887622e9894a9c831f77c809"

needs_sqlite_cli = pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 is not installed")


def test_split_statements_drops_comments_and_blank_parts() -> None:
    script = "-- a comment: with :colon\nCREATE TABLE a (x INT);\n\n-- more\nINSERT INTO a VALUES (1),\n  (2);\n"
    assert split_statements(script) == ["CREATE TABLE a (x INT)", "INSERT INTO a VALUES (1),\n  (2)"]


def test_seed_data_file_has_15_inserts_in_dependency_order() -> None:
    statements = split_statements((SQL_DIR / "seed_data.sql").read_text())
    tables = [s.split("(")[0].split()[2] for s in statements]
    assert tables == TABLES
    assert all(s.startswith("INSERT INTO") for s in statements)


def run_seed_script(path: Path, cwd: Path) -> None:
    subprocess.run(["bash", str(SERVICE_DIR / "seed_registry.sh"), str(path)], cwd=cwd, check=True, capture_output=True)


def sqlite_cli(path: Path, *args: str) -> str:
    return subprocess.run(["sqlite3", str(path), *args], check=True, capture_output=True, text=True).stdout


def rows_dump(path: Path) -> str:
    return "".join(f"-- {t}\n" + sqlite_cli(path, f"SELECT * FROM {t} ORDER BY id") for t in TABLES)


@needs_sqlite_cli
def test_sqlite_rebuild_matches_the_baseline_rows_and_schema(tmp_path: Path) -> None:
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    rebuilt = tmp_path / "registry.db"
    run_seed_script(rebuilt, cwd=other_cwd)  # Works from any working directory.

    assert hashlib.sha256(rows_dump(rebuilt).encode()).hexdigest() == BASELINE_ROWS_SHA256
    assert hashlib.sha256(sqlite_cli(rebuilt, ".schema").encode()).hexdigest() == BASELINE_SCHEMA_SHA256


@needs_sqlite_cli
def test_sqlite_rebuild_has_15_rows_by_table(tmp_path: Path) -> None:
    rebuilt = tmp_path / "registry.db"
    run_seed_script(rebuilt, cwd=tmp_path)
    with sqlite3.connect(rebuilt) as conn:
        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    assert counts == EXPECTED_COUNTS
    assert sum(counts.values()) == 15


# PostgreSQL: skipped unless TEST_DATABASE_URL is set (the fixtures skip).


def schema_engine(pg_base_url: str, schema: str) -> sa.Engine:
    return db.create_engine_for(parse_database_url(with_options(pg_base_url, f"-csearch_path={schema}")))


def table_counts(engine: sa.Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t: conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES}


def table_names(engine: sa.Engine, schema: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"), {"s": schema}
        )
        return {r[0] for r in rows}


def test_seed_postgres_loads_15_rows_by_table(pg_base_url: str, empty_pg_schema: str) -> None:
    engine = schema_engine(pg_base_url, empty_pg_schema)
    seed_postgres(engine)
    assert table_counts(engine) == EXPECTED_COUNTS


def test_second_seed_fails_and_changes_nothing(pg_base_url: str, empty_pg_schema: str) -> None:
    engine = schema_engine(pg_base_url, empty_pg_schema)
    seed_postgres(engine)
    before = table_counts(engine)
    with pytest.raises(sa.exc.ProgrammingError):
        seed_postgres(engine)
    assert table_counts(engine) == before == EXPECTED_COUNTS


def test_seed_into_empty_existing_tables_fails_and_adds_no_rows(pg_base_url: str, empty_pg_schema: str) -> None:
    engine = schema_engine(pg_base_url, empty_pg_schema)
    with engine.begin() as conn:
        for statement in split_statements((SQL_DIR / "postgres_schema.sql").read_text()):
            conn.execute(sa.text(statement))
    with pytest.raises(sa.exc.ProgrammingError):
        seed_postgres(engine)
    assert table_counts(engine) == {t: 0 for t in TABLES}


def test_failed_seed_rolls_back_everything_it_did(pg_base_url: str, empty_pg_schema: str) -> None:
    # Only `plots` exists, so the tables created before it must disappear with the failure.
    engine = schema_engine(pg_base_url, empty_pg_schema)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE plots (x INTEGER)"))
    with pytest.raises(sa.exc.ProgrammingError):
        seed_postgres(engine)
    assert table_names(engine, empty_pg_schema) == {"plots"}


def run_cli(url: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, str(SERVICE_DIR / "scripts" / "seed.py")],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
    )


def test_cli_refuses_a_sqlite_url_and_creates_nothing(tmp_path: Path) -> None:
    result = run_cli("sqlite:///" + str(tmp_path / "x.db"), tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "PostgreSQL only" in output
    assert "Traceback" not in output
    assert not (tmp_path / "x.db").exists()


def test_cli_refuses_when_database_url_is_empty(tmp_path: Path) -> None:
    result = run_cli("", tmp_path)  # Set but empty: the real variable wins over .env and means SQLite.
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "PostgreSQL only" in output
    assert "Traceback" not in output


def test_cli_failure_message_has_no_url_or_password(tmp_path: Path) -> None:
    result = run_cli("postgresql://u:PWMARKER-cli@127.0.0.1:1/db", tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Nothing was changed" in output
    for secret in ("PWMARKER-cli", "127.0.0.1", "postgresql://", "Traceback"):
        assert secret not in output


def test_cli_seeds_an_empty_database_then_refuses_a_second_run(
    pg_base_url: str, empty_pg_schema: str, tmp_path: Path
) -> None:
    url = with_options(pg_base_url, f"-csearch_path={empty_pg_schema}")
    first = run_cli(url, tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Created 5 tables and loaded 15 rows" in first.stdout
    engine = schema_engine(pg_base_url, empty_pg_schema)
    assert table_counts(engine) == EXPECTED_COUNTS

    second = run_cli(url, tmp_path)
    output = second.stdout + second.stderr
    assert second.returncode == 1
    assert "already exist" in output
    assert "Traceback" not in output
    assert table_counts(engine) == EXPECTED_COUNTS


def test_require_postgres_returns_a_postgres_target_unchanged() -> None:
    target = PostgresTarget("postgresql://u:pw@h/db")
    assert require_postgres(target) is target


def test_require_postgres_refuses_a_sqlite_target_with_a_safe_message(tmp_path: Path) -> None:
    with pytest.raises(SeedError) as info:
        require_postgres(SqliteTarget(tmp_path / "x.db"))
    assert str(info.value) == (
        "seed.py loads PostgreSQL only. Set DATABASE_URL to a postgresql:// URL, "
        "or use seed_registry.sh for SQLite."
    )
