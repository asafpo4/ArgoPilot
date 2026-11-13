import logging
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

import db
from db import DB_PATH, DatabaseUnavailable, IntegrityViolation


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[db.Connection]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    connection = db.connect(test_db)
    yield connection
    connection.close()


def insert_farm(conn: db.Connection) -> None:
    conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", ("t1", "A"))


def test_percent_in_sql_is_rejected(conn: db.Connection) -> None:
    with pytest.raises(ValueError, match="SQL must not contain a literal %"):
        conn.execute("SELECT '100%'")


def test_integrity_violation_rolls_back_then_raises(conn: db.Connection) -> None:
    insert_farm(conn)
    with pytest.raises(IntegrityViolation):
        insert_farm(conn)
    assert conn.execute("SELECT count(*) FROM farms WHERE id = 't1'").fetchone()[0] == 0
    insert_farm(conn)
    conn.commit()
    assert conn.execute("SELECT count(*) FROM farms WHERE id = 't1'").fetchone()[0] == 1


def test_busy_database_raises_unavailable_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)
    lock = sqlite3.connect(test_db)
    lock.execute("BEGIN IMMEDIATE")
    connection = db.connect(test_db)
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


def test_missing_file_raises_unavailable(tmp_path: Path) -> None:
    with pytest.raises(DatabaseUnavailable):
        db.connect(tmp_path / "missing.db")


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


def test_lone_surrogate_passes_through(conn: db.Connection) -> None:
    with pytest.raises(UnicodeEncodeError):
        conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", ("t2", "\ud800"))


class FailingCursor:
    rowcount = 3

    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetchone(self) -> None:
        raise self.error

    def fetchall(self) -> None:
        raise self.error


def sqlite_error(name: str) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("boom")
    error.sqlite_errorname = name
    return error


@pytest.mark.parametrize("name", ["SQLITE_BUSY", "SQLITE_LOCKED"])
@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
def test_lock_error_during_fetch_raises_unavailable_and_logs_once(
    conn: db.Connection, caplog: pytest.LogCaptureFixture, name: str, method: str
) -> None:
    result = db.Result(FailingCursor(sqlite_error(name)), conn._translate)
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            getattr(result, method)()
    warnings = [r for r in caplog.records if r.name == "registry.db" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert result.rowcount == 3


@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
def test_other_error_during_fetch_passes_through(conn: db.Connection, method: str) -> None:
    error = sqlite_error("SQLITE_ERROR")
    result = db.Result(FailingCursor(error), conn._translate)
    with pytest.raises(sqlite3.OperationalError) as info:
        getattr(result, method)()
    assert info.value is error


def test_execute_result_fetches_rows_as_dicts(conn: db.Connection) -> None:
    row = conn.execute("SELECT id, name FROM farms ORDER BY id").fetchone()
    assert set(dict(row)) == {"id", "name"}
