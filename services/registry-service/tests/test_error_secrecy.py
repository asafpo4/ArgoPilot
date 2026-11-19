"""Secrets must not survive in what the database layer raises, even in the exception chain.

Each test guards one protection in db.py. Removing the protection must turn its test red.
"""

import shutil
import sqlite3
import traceback
from pathlib import Path

import psycopg
import psycopg.errors
import pytest
import sqlalchemy as sa

import db
from config import ConfigError, PostgresTarget, SqliteTarget, parse_database_url
from db import DB_PATH, DatabaseUnavailable, IntegrityViolation
from fakes import SECRET_PARAM, FailingResult, FakeSAConnection, exception_chain, wrap

# One driver error for each way the layer translates an error.
KINDS = {
    "unavailable": psycopg.errors.AdminShutdown,
    "integrity": psycopg.errors.UniqueViolation,
    "other": psycopg.errors.UndefinedTable,
}


def assert_chain_is_clean(exc: BaseException) -> None:
    chain = exception_chain(exc)
    assert not [e for e in chain if isinstance(e, sa.exc.SQLAlchemyError)]
    assert not [e for e in chain if SECRET_PARAM in str(e)]
    assert SECRET_PARAM not in "".join(traceback.format_exception(exc))


# Protection: parameters are hidden in SQLAlchemy's own error text (hide_parameters=True).


def test_sqlite_engine_hides_parameters_in_error_text(tmp_path: Path) -> None:
    copy = tmp_path / "registry.db"
    shutil.copy(DB_PATH, copy)
    engine = db.create_engine_for(SqliteTarget(copy))
    with engine.connect() as connection:
        with pytest.raises(sa.exc.DBAPIError) as info:
            connection.execute(sa.text("INSERT INTO no_such_table (x) VALUES (:x)"), {"x": SECRET_PARAM})
    assert "INSERT INTO no_such_table" in str(info.value)  # The message exists and shows the SQL.
    assert SECRET_PARAM not in str(info.value)


def test_postgres_engine_hides_parameters_in_error_text(pg_app_url: str) -> None:
    engine = db.create_engine_for(parse_database_url(pg_app_url))
    with engine.connect() as connection:
        with pytest.raises(sa.exc.DBAPIError) as info:
            connection.execute(sa.text("INSERT INTO no_such_table (x) VALUES (:x)"), {"x": SECRET_PARAM})
    assert "INSERT INTO no_such_table" in str(info.value)
    assert SECRET_PARAM not in str(info.value)


# Protection: errors are raised outside the except block, so no SQLAlchemy exception (whose text
# holds the SQL and, if not hidden, the parameters) is left in __cause__ or __context__.


@pytest.mark.parametrize("kind", KINDS)
def test_execute_error_chain_has_no_sqlalchemy_exception(kind: str) -> None:
    conn = db.Connection(FakeSAConnection(execute_error=wrap(KINDS[kind]())))
    with pytest.raises(Exception) as info:
        conn.execute("INSERT INTO t VALUES (:name)", {"name": "x"})
    assert_chain_is_clean(info.value)
    assert info.value.__context__ is None


def test_commit_error_chain_has_no_sqlalchemy_exception() -> None:
    conn = db.Connection(FakeSAConnection(commit_error=wrap(psycopg.errors.SerializationFailure())))
    with pytest.raises(DatabaseUnavailable) as info:
        conn.commit()
    assert_chain_is_clean(info.value)
    assert info.value.__context__ is None


@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
@pytest.mark.parametrize("kind", KINDS)
def test_fetch_error_chain_has_no_sqlalchemy_exception(kind: str, method: str) -> None:
    conn = db.Connection(FakeSAConnection())
    result = db.Result(FailingResult(wrap(KINDS[kind]())), conn._translated)
    with pytest.raises(Exception) as info:
        getattr(result, method)()
    assert_chain_is_clean(info.value)
    assert info.value.__context__ is None


def test_failed_rollback_error_chain_has_no_sqlalchemy_exception() -> None:
    fake = FakeSAConnection(
        execute_error=wrap(psycopg.errors.UniqueViolation()),
        rollback_error=wrap(psycopg.OperationalError(), invalidated=True),
    )
    with pytest.raises(DatabaseUnavailable) as info:
        db.Connection(fake).execute("INSERT INTO t VALUES (:name)", {"name": "x"})
    assert_chain_is_clean(info.value)
    assert info.value.__context__ is None


def test_open_connection_error_chain_holds_no_driver_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise psycopg.OperationalError('FATAL: password authentication failed (PWMARKER-open)')

    monkeypatch.setattr(psycopg, "connect", fail)
    engine = db.create_engine_for(PostgresTarget("postgresql://u:p@127.0.0.1:1/db"))
    with pytest.raises(DatabaseUnavailable) as info:
        db.open_connection(engine)
    assert exception_chain(info.value) == [info.value]
    assert info.value.__context__ is None


def test_engine_factory_error_chain_holds_no_driver_text() -> None:
    target = PostgresTarget("postgresql://u:secr%zzet@127.0.0.1:1/db")
    with pytest.raises(ConfigError) as info:
        db.create_engine_for(target)
    assert exception_chain(info.value) == [info.value]
    assert info.value.__context__ is None


def test_500_path_error_chain_has_no_sqlalchemy_exception(raising_broken_schema_client) -> None:
    marker = "FARM-MARKER-7q"
    with pytest.raises((sqlite3.OperationalError, psycopg.errors.UndefinedTable)) as info:
        raising_broken_schema_client.get(f"/v1/crops/{marker}")
    chain = exception_chain(info.value)
    assert not [e for e in chain if isinstance(e, sa.exc.SQLAlchemyError)]
    assert marker not in "".join(traceback.format_exception(info.value))


# Protection: IntegrityViolation has a fixed message (PostgreSQL's own text can hold key values).


def test_integrity_violation_message_is_fixed_for_a_postgres_error() -> None:
    driver_error = psycopg.errors.UniqueViolation(
        'duplicate key value violates unique constraint "farms_pkey"\n'
        "DETAIL:  Key (id)=(KEYMARKER-5k) already exists."
    )
    conn = db.Connection(FakeSAConnection(execute_error=wrap(driver_error)))
    with pytest.raises(IntegrityViolation) as info:
        conn.execute("INSERT INTO t VALUES (:name)", {"name": "x"})
    assert str(info.value) == "Integrity constraint violated"


def test_integrity_violation_message_is_fixed_for_a_sqlite_error(tmp_path: Path) -> None:
    copy = tmp_path / "registry.db"
    shutil.copy(DB_PATH, copy)
    conn = db.open_connection(db.create_engine_for(SqliteTarget(copy)))
    try:
        conn.execute("INSERT INTO farms (id, name) VALUES ('d1', 'A')")
        with pytest.raises(IntegrityViolation) as info:
            conn.execute("INSERT INTO farms (id, name) VALUES ('d1', 'B')")
    finally:
        conn.close()
    assert str(info.value) == "Integrity constraint violated"
