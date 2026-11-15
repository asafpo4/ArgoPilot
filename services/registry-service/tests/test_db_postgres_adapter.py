import logging
from typing import Any

import psycopg
import psycopg.errors
import pytest

import db
from db import DatabaseUnavailable, IntegrityViolation


class FakeRaw:
    def __init__(
        self,
        execute_error: Exception | None = None,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
        broken: bool = False,
    ) -> None:
        self.broken = broken
        self.rollbacks = 0
        self._execute_error = execute_error
        self._commit_error = commit_error
        self._rollback_error = rollback_error

    def execute(self, sql: str, params: Any = ()) -> Any:
        if self._execute_error:
            raise self._execute_error
        return object()

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


def test_translate_placeholders() -> None:
    assert db.translate_placeholders("a = ? AND b = ?") == "a = %s AND b = %s"


def test_conninfo_sets_timeouts_and_appends_to_existing_options() -> None:
    info = psycopg.conninfo.conninfo_to_dict(
        db.postgres_conninfo("postgresql://u:p@h/db?options=-csearch_path%3Dtest_ab")
    )
    assert info["options"] == "-csearch_path=test_ab -c lock_timeout=5000"
    assert str(info["connect_timeout"]) == "5"
    info = psycopg.conninfo.conninfo_to_dict(db.postgres_conninfo("postgresql://u:p@h/db"))
    assert info["options"] == "-c lock_timeout=5000"
    assert str(info["connect_timeout"]) == "5"


@pytest.mark.parametrize(
    ("exc", "broken", "expected"),
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
def test_classification_table(exc: Exception, broken: bool, expected: str) -> None:
    assert db.classify_postgres_error(exc, broken) == expected


def test_integrity_error_rolls_back_then_raises() -> None:
    raw = FakeRaw(execute_error=psycopg.errors.UniqueViolation())
    conn = db.PostgresConnection(raw)
    with pytest.raises(IntegrityViolation):
        conn.execute("INSERT INTO t VALUES (?)", (1,))
    assert raw.rollbacks == 1


def registry_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "registry.db" and r.levelno == logging.WARNING]


def test_failed_rollback_becomes_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    raw = FakeRaw(
        execute_error=psycopg.errors.UniqueViolation(),
        rollback_error=psycopg.OperationalError(),
        broken=True,
    )
    conn = db.PostgresConnection(raw)
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            conn.execute("INSERT INTO t VALUES (?)", (1,))
    assert raw.rollbacks == 1
    assert len(registry_warnings(caplog)) == 1


def test_commit_errors_are_translated(caplog: pytest.LogCaptureFixture) -> None:
    conn = db.PostgresConnection(FakeRaw(commit_error=psycopg.errors.SerializationFailure()))
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        with pytest.raises(DatabaseUnavailable):
            conn.commit()
    assert len(registry_warnings(caplog)) == 1


def test_unavailable_log_never_contains_password(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.connect_postgres("postgresql://u:p%40ss%3Aw%2Frd@127.0.0.1:1/db")
    for secret in ("p@ss", "p%40ss", "w/rd"):
        assert secret not in caplog.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_other_errors_pass_through_unchanged() -> None:
    error = psycopg.errors.UndefinedTable()
    conn = db.PostgresConnection(FakeRaw(execute_error=error))
    with pytest.raises(psycopg.errors.UndefinedTable) as info:
        conn.execute("SELECT 1")
    assert info.value is error


def test_malformed_percent_escape_in_password_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.connect_postgres("postgresql://u:secr%zzet@127.0.0.1:1/db")
    for secret in ("secr%zzet", "secr", "zzet"):
        assert secret not in caplog.text
    assert len(registry_warnings(caplog)) == 1


def test_non_operational_connect_error_text_is_withheld(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise psycopg.ProgrammingError("bad option for secretpw")

    monkeypatch.setattr(psycopg, "connect", fail)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(DatabaseUnavailable):
            db.connect_postgres("postgresql://u:p@127.0.0.1:1/db")
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
            db.connect_postgres("postgresql://u:urlpw@127.0.0.1:5432/db")
    assert "password authentication failed" in caplog.text
    assert "urlpw" not in caplog.text
    assert len(registry_warnings(caplog)) == 1
