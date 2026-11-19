import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
import sqlalchemy as sa

from config import parse_database_url
from db import DB_PATH, create_engine_for
from seeding import seed_postgres
from pg_support import (
    TestEnv,
    capture_developer_database_url,
    check_comparable_test_url,
    check_not_developer_database,
    with_options,
)

SERVICE_DIR = Path(__file__).resolve().parent.parent
TABLES = ["farms", "crops", "soils", "emitters", "plots"]


def test_capture_ignores_empty_and_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert capture_developer_database_url() is None
    monkeypatch.setenv("DATABASE_URL", "")
    assert capture_developer_database_url() is None
    monkeypatch.setenv("DATABASE_URL", "postgresql://h/d")
    assert capture_developer_database_url() == "postgresql://h/d"


def test_urls_kept_only_in_dot_env_are_seen_by_the_test_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://dev@devhost/registry\n"
                        "TEST_DATABASE_URL=postgresql://t@testhost/t\n")
    assert capture_developer_database_url(env_file) == "postgresql://dev@devhost/registry"
    assert TestEnv(_env_file=env_file).TEST_DATABASE_URL == "postgresql://t@testhost/t"


def test_safety_check_refuses_a_developer_url_kept_only_in_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://dev@devhost/registry\n")
    developer = capture_developer_database_url(env_file)
    with pytest.raises(pytest.fail.Exception, match="^refusing to run"):
        check_not_developer_database("postgresql://dev@devhost/registry", developer)


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


def test_check_refuses_host_lists_given_in_the_query() -> None:
    for bad in (
        "postgresql://u@localhost/registry?host=localhost,other.invalid",
        "postgresql://u@localhost/registry?host=,localhost",
        "postgresql://u@other.invalid/registry?host=localhost,other.invalid",
    ):
        with pytest.raises(pytest.fail.Exception, match="^refusing to run") as info:
            check_comparable_test_url(bad)
        assert bad not in str(info.value)


def test_same_database_is_conservative_for_host_lists() -> None:
    from config import same_database

    dev = "postgresql://u@localhost/registry"
    assert same_database("postgresql://u@localhost/registry?host=localhost,other.invalid", dev)
    assert same_database(dev, "postgresql://u@other.invalid/registry?host=other.invalid,localhost")
    assert not same_database("postgresql://u@a/registry?host=a,b", dev)
    assert not same_database("postgresql://u@localhost/x?host=localhost,b", dev.replace("registry", "y"))


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
    engine = create_engine_for(parse_database_url(with_options(pg_base_url, f"-csearch_path={pg_schema}")))
    with pytest.raises(sa.exc.ProgrammingError):
        seed_postgres(engine)


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


def test_check_refuses_ports_libpq_normalizes_but_the_identity_cannot_read() -> None:
    for bad in (
        "postgresql://u@localhost/registry?port=%205432",
        "postgresql://u@localhost/registry?port=5432%20",
        "postgresql://u@localhost/registry?port=5432%09",
        "postgresql://u@localhost/registry?port=+5432",
        "postgresql://u@localhost:+5432/registry",
        "postgresql://u@localhost/registry?port=0",
        "postgresql://u@localhost/registry?port=65536",
        "postgresql://u@localhost/registry?port=1e3",
        "postgresql://u@localhost/registry?port=%D9%A5",
        "postgresql://u@localhost/registry?port=5432,5433",
        "postgresql://u@localhost/registry?port=",
    ):
        with pytest.raises(pytest.fail.Exception, match="^refusing to run") as info:
            check_comparable_test_url(bad)
        assert bad not in str(info.value)
    for good in (
        "postgresql://u@localhost/registry?port=05432",
        "postgresql://u@localhost/registry?port=65535",
        "postgresql://u@localhost:5432/registry",
    ):
        check_comparable_test_url(good)
