import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from db import DB_PATH
from pg_support import (
    capture_developer_database_url,
    check_comparable_test_url,
    check_not_developer_database,
    with_options,
)

SERVICE_DIR = Path(__file__).resolve().parent.parent
TABLES = ["farms", "crops", "soils", "emitters", "plots"]


def test_capture_ignores_empty_and_returns_value() -> None:
    assert capture_developer_database_url({}) is None
    assert capture_developer_database_url({"DATABASE_URL": ""}) is None
    assert capture_developer_database_url({"DATABASE_URL": "postgresql://h/d"}) == "postgresql://h/d"


def test_check_refuses_on_match() -> None:
    dev = "postgresql://u:p@127.0.0.1:5432/registry"
    for test_url in (
        dev,
        "postgresql://u:p@localhost:5432/registry",
        "postgresql://u:p@127.0.0.1/registry",
    ):
        with pytest.raises(pytest.fail.Exception, match="^refusing to run"):
            check_not_developer_database(test_url, dev)
    with pytest.raises(pytest.fail.Exception, match="^refusing to run"):
        check_not_developer_database("postgresql://u:p@localhost/registry", dev)
    check_not_developer_database("postgresql://u:p@127.0.0.1:5432/other", dev)
    check_not_developer_database(dev, None)
    check_not_developer_database(dev, "sqlite:///x.db")


def test_check_refuses_test_urls_it_cannot_compare() -> None:
    for bad in (
        "host=h dbname=prod",
        "postgresql:///registry?host=/run/postgresql",
        "mysql://h/db",
    ):
        with pytest.raises(pytest.fail.Exception, match="^refusing to run") as info:
            check_comparable_test_url(bad)
        assert bad not in str(info.value)
    check_comparable_test_url("postgresql://u:p@h:5432/db")
    check_comparable_test_url("postgres://h/db")


def test_check_refuses_test_urls_with_parts_the_comparison_cannot_read() -> None:
    for bad in (
        "postgresql://u@h/db?service=x",
        "postgresql://u@whatever/db?hostaddr=127.0.0.1",
        "postgresql://u@h1,h2/db",
        "postgresql://u:p@h:5432/db?sslmode=require&SERVICE=x",
    ):
        with pytest.raises(pytest.fail.Exception, match="^refusing to run") as info:
            check_comparable_test_url(bad)
        assert bad not in str(info.value)
    check_comparable_test_url("postgresql://u:p@h:5432/db")


def test_session_start_capture_happens_before_fixtures() -> None:
    url = "postgresql://u:p@nohost.invalid:5432/prod"
    env = {**os.environ, "DATABASE_URL": url, "TEST_DATABASE_URL": url}
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_farms.py::test_list_farms_returns_both_seeded_farms",
            "-k", "postgres", "-p", "no:cacheprovider", "-q",
        ],
        cwd=SERVICE_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + result.stderr
    assert "refusing to run" in output
    assert result.returncode != 0
    assert "nohost.invalid" not in output
    assert "failed to resolve host" not in output
    assert "could not translate host name" not in output
    assert " passed" not in output


def schema_connection(base_url: str, schema: str) -> psycopg.Connection:
    return psycopg.connect(with_options(base_url, f"-csearch_path={schema}"))


def test_schema_script_fails_on_second_run(pg_base_url: str, pg_schema: str) -> None:
    script = (SERVICE_DIR / "sql" / "postgres_schema.sql").read_text()
    with schema_connection(pg_base_url, pg_schema) as conn:
        with pytest.raises(psycopg.errors.DuplicateTable):
            conn.execute(script)


def test_pg_schema_contains_demo_data(pg_base_url: str, pg_schema: str) -> None:
    with schema_connection(pg_base_url, pg_schema) as conn:
        assert conn.execute("SELECT count(*) FROM farms").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM plots").fetchone()[0] == 4


def test_catalogue_and_demo_rows_match_sqlite_seed(
    pg_base_url: str, pg_schema: str, tmp_path: Path
) -> None:
    copy = tmp_path / "registry.db"
    shutil.copy(DB_PATH, copy)
    lite = sqlite3.connect(copy)
    try:
        compare_tables(lite, pg_base_url, pg_schema)
    finally:
        lite.close()


def compare_tables(lite: sqlite3.Connection, pg_base_url: str, pg_schema: str) -> None:
    with schema_connection(pg_base_url, pg_schema) as pg:
        for table in TABLES:
            cursor = lite.execute(f"SELECT * FROM {table}")
            columns = [d[0] for d in cursor.description]
            lite_rows = sorted(tuple(r) for r in cursor.fetchall())
            pg_rows = sorted(
                tuple(r) for r in pg.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
            )
            assert pg_rows == lite_rows, table
