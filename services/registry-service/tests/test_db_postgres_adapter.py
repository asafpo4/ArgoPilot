import logging
import traceback
from typing import Any

import psycopg
import psycopg.errors
import pytest
import sqlalchemy as sa

import db
from config import ConfigError, PostgresTarget
from db import DatabaseUnavailable, IntegrityViolation


def wrap(orig: Exception, invalidated: bool = False) -> sa.exc.StatementError:
    """What SQLAlchemy raises around a driver error. Its text holds the SQL and the parameters."""
    return sa.exc.DBAPIError.instance(
        "INSERT INTO t VALUES (:name)",
        {"name": "SECRET-FARM-NAME"},
        orig,
        psycopg.Error,
        connection_invalidated=invalidated,
    )


class FakeCursorResult:
    rowcount = 1


class FakeSAConnection:
    def __init__(
        self,
        execute_error: Exception | None = None,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self.rollbacks = 0
        self._execute_error = execute_error
        self._commit_error = commit_error
        self._rollback_error = rollback_error

    def execute(self, statement: Any, params: Any = None) -> Any:
        if self._execute_error:
            raise self._execute_error
        return FakeCursorResult()

    def commit(self) -> None:
        if self._commit_error:
            raise self._commit_error

    def rollback(self) -> None:
        self.rollbacks += 1
        if self._rollback_error:
            raise self._rollback_error


def sqlstate_error(code: str) -> psycopg.Error:
    cls = psycopg.errors.lookup(code)
    return cls()


def test_engine_uses_no_connection_pool() -> None:
    engine: Any = db.create_engine_for(PostgresTarget("postgresql://u:p@h/db"))
    assert type(engine.pool).__name__ == "NullPool"


@pytest.mark.parametrize(
    ("exc", "invalidated", "expected"),
    [
        (sqlstate_error("08006"), False, "unavailable"),
        (sqlstate_error("08001"), False, "unavailable"),
        (sqlstate_error("08003"), False, "unavailable"),
        *[(sqlstate_error(code), False, "unavailable") for code in sorted(db.PG_UNAVAILABLE_SQLSTATES)],
        (psycopg.errors.AdminShutdown(), False, "unavailable"),
        (psycopg.OperationalError(), True, "unavailable"),
        (psycopg.OperationalError(), False, "other"),
        (psycopg.errors.UniqueViolation(), False, "integrity"),
        (psycopg.errors.ForeignKeyViolation(), False, "integrity"),
        (psycopg.errors.UndefinedTable(), False, "other"),
        (psycopg.DataError(), False, "other"),
        (UnicodeEncodeError("utf-8", "x", 0, 1, "bad"), False, "other"),
    ],
)
def test_classification_table(exc: Exception, invalidated: bool, expected: str) -> None:
    assert db.classify_error(wrap(exc, invalidated), invalidated) == expected


def test_integrity_error_rolls_back_then_raises() -> None:
    fake = FakeSAConnection(execute_error=wrap(psycopg.errors.UniqueViolation()))
    conn = db.Connection(fake)
    with pytest.raises(IntegrityViolation):
        conn.execute("INSERT INTO t VALUES (:name)", {"name": "x"})
    assert fake.rollbacks == 1


def registry_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "registry.db" and r.levelno == logging.WARNING]


def test_failed_rollback_becomes_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeSAConnection(
        execute_error=wrap(psycopg.errors.UniqueViolation()),
        rollback_error=wrap(psycopg.OperationalError(), invalidated=True),
    )
    conn = db.Connection(fake)
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            conn.execute("INSERT INTO t VALUES (:name)", {"name": "x"})
    assert fake.rollbacks == 1
    assert len(registry_warnings(caplog)) == 1


def test_commit_errors_are_translated(caplog: pytest.LogCaptureFixture) -> None:
    conn = db.Connection(FakeSAConnection(commit_error=wrap(psycopg.errors.SerializationFailure())))
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            conn.commit()
    assert len(registry_warnings(caplog)) == 1


def test_log_never_contains_sql_parameters(caplog: pytest.LogCaptureFixture) -> None:
    # SQLAlchemy's own message would hold the parameter; the log must hold the driver error only.
    error = wrap(psycopg.errors.AdminShutdown("terminating connection due to administrator command"))
    assert "SECRET-FARM-NAME" in str(error)
    conn = db.Connection(FakeSAConnection(execute_error=error))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            conn.execute("INSERT INTO t VALUES (:name)", {"name": "SECRET-FARM-NAME"})
    assert "SECRET-FARM-NAME" not in caplog.text
    assert "terminating connection" in caplog.text
    assert len(registry_warnings(caplog)) == 1


def test_unavailable_error_carries_no_sqlalchemy_text() -> None:
    error = wrap(psycopg.errors.AdminShutdown())
    secret = str(error.params["name"])  # Kept out of this file's own source lines on purpose.
    conn = db.Connection(FakeSAConnection(execute_error=error))
    with pytest.raises(DatabaseUnavailable) as info:
        conn.execute("INSERT INTO t VALUES (:name)", {"name": secret})
    assert secret in str(error)
    assert secret not in "".join(traceback.format_exception(info.value))


def test_unavailable_log_never_contains_password(caplog: pytest.LogCaptureFixture) -> None:
    target = PostgresTarget("postgresql://u:p%40ss%3Aw%2Frd@127.0.0.1:1/db")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.open_connection(db.create_engine_for(target))
    for secret in ("p@ss", "p%40ss", "w/rd"):
        assert secret not in caplog.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_other_errors_pass_through_unchanged() -> None:
    error = psycopg.errors.UndefinedTable()
    conn = db.Connection(FakeSAConnection(execute_error=wrap(error)))
    with pytest.raises(psycopg.errors.UndefinedTable) as info:
        conn.execute("SELECT 1")
    assert info.value is error


def test_malformed_percent_escape_in_password_never_leaves_the_engine_factory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Startup validation rejects this URL first; this is the second line of defence.
    target = PostgresTarget("postgresql://u:secr%zzet@127.0.0.1:1/db")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ConfigError) as info:
            db.create_engine_for(target)
    for secret in ("secr%zzet", "secr", "zzet"):
        assert secret not in str(info.value)
        assert secret not in "".join(traceback.format_exception(info.value))
        assert secret not in caplog.text


def test_non_operational_connect_error_text_is_withheld(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise psycopg.ProgrammingError("bad option for secretpw")

    monkeypatch.setattr(psycopg, "connect", fail)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.open_connection(db.create_engine_for(PostgresTarget("postgresql://u:p@127.0.0.1:1/db")))
    assert "secretpw" not in caplog.text
    assert "ProgrammingError" in caplog.text
    assert len(registry_warnings(caplog)) == 1


def test_operational_connect_error_keeps_the_cause(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise psycopg.OperationalError(
            'connection to server at "127.0.0.1", port 5432 failed: '
            'FATAL:  password authentication failed for user "u"'
        )

    monkeypatch.setattr(psycopg, "connect", fail)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.open_connection(
                db.create_engine_for(PostgresTarget("postgresql://u:urlpw@127.0.0.1:5432/db"))
            )
    assert "password authentication failed" in caplog.text
    assert "urlpw" not in caplog.text
    assert len(registry_warnings(caplog)) == 1
