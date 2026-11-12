import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db import DB_PATH, Connection, connect, get_db
from main import app


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


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    use_database(test_db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unavailable_client(tmp_path: Path) -> Iterator[TestClient]:
    # This file is never created, so connecting with mode=rw fails.
    use_database(tmp_path / "missing.db")
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


@pytest.fixture
def broken_schema_client(tmp_path: Path) -> Iterator[TestClient]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    drop = sqlite3.connect(test_db)
    drop.execute("DROP TABLE crops")
    drop.commit()
    drop.close()
    use_database(test_db)
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
