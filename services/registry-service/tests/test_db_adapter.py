import logging
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

import db
from config import SqliteTarget
from db import DB_PATH, DatabaseUnavailable, IntegrityViolation


def open_sqlite(path: Path) -> db.Connection:
    return db.open_connection(db.create_engine_for(SqliteTarget(path)))


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[db.Connection]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    connection = open_sqlite(test_db)
    yield connection
    connection.close()


def insert_farm(conn: db.Connection, name: str = "A") -> None:
    conn.execute("INSERT INTO farms (id, name) VALUES (:id, :name)", {"id": "t1", "name": name})


def farm_count(conn: db.Connection) -> int:
    return conn.execute("SELECT count(*) AS n FROM farms WHERE id = 't1'").fetchone()["n"]


def test_literal_percent_in_sql_is_accepted(conn: db.Connection) -> None:
    assert conn.execute("SELECT '100%' AS v").fetchone()["v"] == "100%"


def test_colon_in_a_bound_value_is_kept(conn: db.Connection) -> None:
    insert_farm(conn, "a:b %s :c")
    assert conn.execute("SELECT name FROM farms WHERE id = 't1'").fetchone()["name"] == "a:b %s :c"


def test_integrity_violation_rolls_back_then_raises(conn: db.Connection) -> None:
    insert_farm(conn)
    with pytest.raises(IntegrityViolation):
        insert_farm(conn)
    assert farm_count(conn) == 0
    insert_farm(conn)
    conn.commit()
    assert farm_count(conn) == 1


def test_busy_database_raises_unavailable_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    lock = sqlite3.connect(test_db)
    lock.execute("BEGIN IMMEDIATE")
    connection = open_sqlite(test_db)
    try:
        connection.execute("PRAGMA busy_timeout = 100")
        with caplog.at_level(logging.WARNING, logger="registry.db"):
            with pytest.raises(DatabaseUnavailable):
                insert_farm(connection)
        warnings = [r for r in caplog.records if r.name == "registry.db" and r.levelno == logging.WARNING]
        assert len(warnings) == 1
    finally:
        connection.close()
        lock.rollback()
        lock.close()


def test_busy_log_never_contains_sql_parameters(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    lock = sqlite3.connect(test_db)
    lock.execute("BEGIN IMMEDIATE")
    connection = open_sqlite(test_db)
    try:
        connection.execute("PRAGMA busy_timeout = 100")
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DatabaseUnavailable):
                insert_farm(connection, "SECRET-FARM-NAME")
        assert "SECRET-FARM-NAME" not in caplog.text
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    finally:
        connection.close()
        lock.rollback()
        lock.close()


def test_missing_file_raises_unavailable(tmp_path: Path) -> None:
    with pytest.raises(DatabaseUnavailable):
        open_sqlite(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_integrity_violation_writes_no_log(
    conn: db.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    insert_farm(conn)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IntegrityViolation):
            insert_farm(conn)
    assert caplog.records == []


def test_other_errors_pass_through_unchanged(conn: db.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM no_such_table")


def test_lone_surrogate_reaches_the_caller_as_unicode_encode_error(conn: db.Connection) -> None:
    # SQLAlchemy wraps this in StatementError; the caller must still get the original error.
    with pytest.raises(UnicodeEncodeError):
        conn.execute("INSERT INTO farms (id, name) VALUES (:id, :name)", {"id": "t2", "name": "\ud800"})


class FailingMappings:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetchone(self) -> None:
        raise self.error

    def fetchall(self) -> None:
        raise self.error


class FailingResult:
    rowcount = 3

    def __init__(self, error: Exception) -> None:
        self.error = error

    def mappings(self) -> FailingMappings:
        return FailingMappings(self.error)


def sqlite_error(name: str) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("boom")
    error.sqlite_errorname = name
    return error


def wrapped(orig: Exception) -> sa.exc.DBAPIError:
    return sa.exc.DBAPIError.instance("SELECT 1", {"p": 1}, orig, sqlite3.Error)


@pytest.mark.parametrize("name", ["SQLITE_BUSY", "SQLITE_LOCKED"])
@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
def test_lock_error_during_fetch_raises_unavailable_and_logs_once(
    conn: db.Connection, caplog: pytest.LogCaptureFixture, name: str, method: str
) -> None:
    result = db.Result(FailingResult(wrapped(sqlite_error(name))), conn._translate)
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            getattr(result, method)()
    warnings = [r for r in caplog.records if r.name == "registry.db" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert result.rowcount == 3


@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
def test_other_error_during_fetch_passes_through(conn: db.Connection, method: str) -> None:
    error = sqlite_error("SQLITE_ERROR")
    result = db.Result(FailingResult(wrapped(error)), conn._translate)
    with pytest.raises(sqlite3.OperationalError) as info:
        getattr(result, method)()
    assert info.value is error


def test_execute_result_fetches_rows_as_dicts(conn: db.Connection) -> None:
    row = conn.execute("SELECT id, name FROM farms ORDER BY id").fetchone()
    assert isinstance(row, dict)
    assert set(row) == {"id", "name"}


def test_rowcount_survives_the_commit(conn: db.Connection) -> None:
    insert_farm(conn)
    result = conn.execute("DELETE FROM farms WHERE id = :id", {"id": "t1"})
    conn.commit()
    assert result.rowcount == 1


def test_engine_uses_no_connection_pool() -> None:
    engine: Any = db.create_engine_for(SqliteTarget(Path("/nonexistent/x.db")))
    assert type(engine.pool).__name__ == "NullPool"
