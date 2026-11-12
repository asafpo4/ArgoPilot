import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

import config as service_config  # Importing it loads .env, as the service does.
import pg_support
from db import DB_PATH, Connection, connect, connect_postgres, get_db
from main import app

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def pytest_configure(config: pytest.Config) -> None:
    # Before any fixture runs: the autouse fixture below overwrites DATABASE_URL.
    assert service_config  # .env is loaded by now
    pg_support.DEVELOPER_DATABASE_URL = pg_support.capture_developer_database_url(os.environ)


@pytest.fixture(autouse=True)
def isolate_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real environment variable beats .env, so startup never reads the developer's .env.
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(DB_PATH))


def use_database(path: Path) -> None:
    def override_get_db() -> Iterator[Connection]:
        conn = connect(path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def pg_base_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    pg_support.check_comparable_test_url(url)
    pg_support.check_not_developer_database(url, pg_support.DEVELOPER_DATABASE_URL)
    return url


@pytest.fixture
def pg_schema(pg_base_url: str) -> Iterator[str]:
    name = pg_support.SCHEMA_PREFIX + uuid.uuid4().hex
    options = f"-csearch_path={name}"
    with psycopg.connect(pg_base_url, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{name}"')
        try:
            with psycopg.connect(
                pg_support.with_options(pg_base_url, options), autocommit=True
            ) as scoped:
                for script in ("postgres_schema.sql", "demo_data.sql"):
                    scoped.execute((SQL_DIR / script).read_text())
            yield name
        finally:
            admin.execute(f'DROP SCHEMA "{name}" CASCADE')


@pytest.fixture
def pg_app_url(pg_base_url: str, pg_schema: str) -> str:
    return pg_support.with_options(pg_base_url, f"-csearch_path={pg_schema}")


@dataclass
class TestDatabase:
    __test__ = False

    backend: str
    connect: Callable[[], Connection]


@pytest.fixture(params=["sqlite", "postgres"])
def database(request: pytest.FixtureRequest, tmp_path: Path) -> TestDatabase:
    if request.param == "sqlite":
        test_db = tmp_path / "registry.db"
        shutil.copy(DB_PATH, test_db)
        return TestDatabase("sqlite", lambda: connect(test_db))
    url = request.getfixturevalue("pg_app_url")
    return TestDatabase("postgres", lambda: connect_postgres(url))


@pytest.fixture
def client(
    request: pytest.FixtureRequest,
    database: TestDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    if database.backend == "sqlite":
        use_database(tmp_path / "registry.db")
    else:
        monkeypatch.setenv("DATABASE_URL", request.getfixturevalue("pg_app_url"))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(params=["sqlite", "postgres"])
def unavailable_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    if request.param == "sqlite":
        # This file is never created, so connecting with mode=rw fails.
        use_database(tmp_path / "missing.db")
    else:
        base = request.getfixturevalue("pg_base_url")
        monkeypatch.setenv("DATABASE_URL", pg_support.with_url_parts(base, port=1))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def broken_client() -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Connection]:
        raise RuntimeError("secret internal message")
        yield

    app.dependency_overrides[get_db] = override_get_db
    # A catch-all handler makes TestClient re-raise the error by default, so turn that off.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(params=["sqlite", "postgres"])
def broken_schema_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    if request.param == "sqlite":
        test_db = tmp_path / "registry.db"
        shutil.copy(DB_PATH, test_db)
        drop = sqlite3.connect(test_db)
        drop.execute("DROP TABLE crops")
        drop.commit()
        drop.close()
        use_database(test_db)
    else:
        url = request.getfixturevalue("pg_app_url")
        schema = request.getfixturevalue("pg_schema")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP TABLE "{schema}".crops CASCADE')
        monkeypatch.setenv("DATABASE_URL", url)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def locked_client(tmp_path: Path) -> Iterator[TestClient]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    lock = sqlite3.connect(test_db)
    lock.execute("BEGIN IMMEDIATE")  # Holds the write lock until the test ends.

    def override_get_db() -> Iterator[Connection]:
        conn = connect(test_db)
        # Wait 0.1 s for the lock instead of the default 5 s, so the test stays fast.
        conn.execute("PRAGMA busy_timeout = 100")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    lock.rollback()
    lock.close()
