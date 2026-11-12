import logging
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

import psycopg
import psycopg.errors
import psycopg.rows
from fastapi import Request
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import config
from config import PostgresTarget, SqliteTarget

logger = logging.getLogger("registry.db")

DB_PATH = config.DEFAULT_SQLITE_PATH

# These SQLite codes mean the database cannot be used right now (judgment log, entry 6).
UNAVAILABLE_SQLITE_ERRORS = {"SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_CANTOPEN"}

# These PostgreSQL SQLSTATEs mean the database cannot be used right now (class 08 is added in code).
PG_UNAVAILABLE_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300", "55P03", "40001", "40P01"})


class DatabaseUnavailable(Exception):
    """The database cannot be used right now."""


class IntegrityViolation(Exception):
    """A constraint was violated. The transaction has been rolled back."""


class Result:
    """A cursor-like result. Errors raised while fetching go through the same translation."""

    def __init__(self, cursor: Any, translate: Callable[[Exception], None]) -> None:
        self._cursor = cursor
        self._translate = translate

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> Any:
        try:
            return self._cursor.fetchone()
        except Exception as exc:
            self._translate(exc)

    def fetchall(self) -> list[Any]:
        try:
            return self._cursor.fetchall()
        except Exception as exc:
            self._translate(exc)


class Connection:
    """Driver-neutral connection. Subclasses set `raw` and override the two hooks."""

    raw: Any

    def _prepare(self, sql: str) -> str:
        return sql

    def _classify(self, exc: Exception) -> Literal["unavailable", "integrity", "other"]:
        return "other"

    def _unavailable(self, exc: Exception) -> DatabaseUnavailable:
        logger.warning(
            "Database unavailable: %s %s: %s",
            type(exc).__name__,
            getattr(exc, "sqlite_errorname", None) or getattr(exc, "sqlstate", None) or "",
            exc,
        )
        return DatabaseUnavailable("Database unavailable")

    def _translate(self, exc: Exception) -> None:
        kind = self._classify(exc)
        if kind == "unavailable":
            raise self._unavailable(exc) from exc
        if kind == "integrity":
            try:
                self.rollback()
            except Exception as rollback_exc:
                raise self._unavailable(rollback_exc) from exc
            raise IntegrityViolation(str(exc)) from exc
        raise exc

    def execute(self, sql: str, params: Sequence = ()) -> Result:
        if "%" in sql:
            raise ValueError("SQL must not contain a literal %")
        try:
            return Result(self.raw.execute(self._prepare(sql), params), self._translate)
        except Exception as exc:
            self._translate(exc)

    def commit(self) -> None:
        try:
            self.raw.commit()
        except Exception as exc:
            self._translate(exc)

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


class SqliteConnection(Connection):
    def __init__(self, raw: sqlite3.Connection) -> None:
        self.raw = raw

    def _classify(self, exc: Exception) -> Literal["unavailable", "integrity", "other"]:
        if isinstance(exc, sqlite3.IntegrityError):
            return "integrity"
        if getattr(exc, "sqlite_errorname", None) in UNAVAILABLE_SQLITE_ERRORS:
            return "unavailable"
        return "other"


def connect(path: Path) -> Connection:
    # mode=rw: fail if the file is missing, instead of creating an empty one.
    # check_same_thread=False: each request has its own connection, and that request's steps
    # run one after another, so no connection is used by two threads at the same time.
    try:
        raw = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, check_same_thread=False)
    except sqlite3.Error as exc:
        conn = SqliteConnection.__new__(SqliteConnection)
        conn._translate(exc)
        raise
    raw.row_factory = sqlite3.Row
    conn = SqliteConnection(raw)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def translate_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


def postgres_conninfo(url: str) -> str:
    params = conninfo_to_dict(url)
    options = params.get("options")
    lock_option = "-c lock_timeout=5000"
    params["options"] = f"{options} {lock_option}" if options else lock_option
    params["connect_timeout"] = 5
    return make_conninfo(**params)


def classify_postgres_error(
    exc: Exception, broken: bool
) -> Literal["unavailable", "integrity", "other"]:
    if isinstance(exc, psycopg.errors.IntegrityError):
        return "integrity"
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate and (sqlstate in PG_UNAVAILABLE_SQLSTATES or sqlstate.startswith("08")):
        return "unavailable"
    if isinstance(exc, psycopg.OperationalError) and broken:
        return "unavailable"
    return "other"


class PostgresConnection(Connection):
    def __init__(self, raw: psycopg.Connection) -> None:
        self.raw = raw

    def _prepare(self, sql: str) -> str:
        return translate_placeholders(sql)

    def _classify(self, exc: Exception) -> Literal["unavailable", "integrity", "other"]:
        return classify_postgres_error(exc, self.raw.broken)


def connect_postgres(url: str) -> Connection:
    try:
        raw = psycopg.connect(postgres_conninfo(url), row_factory=psycopg.rows.dict_row)
    except psycopg.Error as exc:
        # Log only the class, SQLSTATE and message: never the URL, pgconn or parameters.
        logger.warning(
            "Database unavailable: %s %s: %s", type(exc).__name__, exc.sqlstate or "", exc
        )
        raise DatabaseUnavailable("Database unavailable") from exc
    return PostgresConnection(raw)


def connect_target(target: SqliteTarget | PostgresTarget) -> Connection:
    if isinstance(target, SqliteTarget):
        return connect(target.path)
    return connect_postgres(target.url)


def get_db(request: Request) -> Iterator[Connection]:
    conn = connect_target(request.app.state.db_target)
    try:
        yield conn
    finally:
        conn.close()
