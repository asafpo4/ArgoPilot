"""Fakes for the database error tests: SQLAlchemy errors and connections, with no server."""

from typing import Any

import psycopg
import sqlalchemy as sa

# A bound parameter value. SQLAlchemy's own error text holds it unless parameters are hidden.
SECRET_PARAM = "SECRET-FARM-NAME"


def wrap(orig: Exception, invalidated: bool = False) -> sa.exc.StatementError:
    """What SQLAlchemy raises around a driver error. Its text holds the SQL and the parameters."""
    return sa.exc.DBAPIError.instance(
        "INSERT INTO t VALUES (:name)",
        {"name": SECRET_PARAM},
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
