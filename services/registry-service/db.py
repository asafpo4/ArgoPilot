import logging
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Literal, NoReturn
from urllib.parse import quote

import psycopg
import psycopg.errors
import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.pool import NullPool

import config
from config import PostgresTarget, SqliteTarget

logger = logging.getLogger("registry.db")

DB_PATH = config.DEFAULT_SQLITE_PATH

# These SQLite codes mean the database cannot be used right now (judgment log, entry 6).
UNAVAILABLE_SQLITE_ERRORS = {"SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_CANTOPEN"}

# These PostgreSQL SQLSTATEs mean the database cannot be used right now (class 08 is added in code).
PG_UNAVAILABLE_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300", "55P03", "40001", "40P01"})


def driver_error(exc: Exception) -> Exception:
    """The error the database driver raised, under SQLAlchemy's wrapper.

    SQLAlchemy wraps driver errors (and any other error raised while running a statement) in
    StatementError. Its text holds the SQL, so it is never logged; the driver error is.
    """
    orig = getattr(exc, "orig", None)
    if isinstance(exc, sa.exc.StatementError) and orig is not None:
        return orig
    return exc


def _log_unavailable(exc: Exception) -> None:
    """Log one WARNING for a DatabaseUnavailable. Never formats pgconn, repr(exc) or the URL.

    `exc` is the driver error, not SQLAlchemy's wrapper. The message text is included only for
    errors known not to carry connection secrets: SQLite errors and psycopg.OperationalError
    (server and network failures).
    """
    code = getattr(exc, "sqlite_errorname", None) or getattr(exc, "sqlstate", None) or ""
    if isinstance(exc, (sqlite3.Error, psycopg.OperationalError)):
        logger.warning("Database unavailable: %s %s: %s", type(exc).__name__, code, exc)
    else:
        logger.warning(
            "Database unavailable: %s %s: invalid PostgreSQL connection settings (details withheld)",
            type(exc).__name__,
            code,
        )


class DatabaseUnavailable(Exception):
    """The database cannot be used right now."""


class IntegrityViolation(Exception):
    """A constraint was violated. The transaction has been rolled back."""


def classify_error(
    exc: Exception, invalidated: bool = False
) -> Literal["unavailable", "integrity", "other"]:
    """Decide what an error means. `invalidated` says SQLAlchemy found the connection dead."""
    driver = driver_error(exc)
    if isinstance(exc, sa.exc.IntegrityError) or isinstance(
        driver, (sqlite3.IntegrityError, psycopg.errors.IntegrityError)
    ):
        return "integrity"
    if getattr(driver, "sqlite_errorname", None) in UNAVAILABLE_SQLITE_ERRORS:
        return "unavailable"
    sqlstate = getattr(driver, "sqlstate", None)
    if sqlstate and (sqlstate in PG_UNAVAILABLE_SQLSTATES or sqlstate.startswith("08")):
        return "unavailable"
    if invalidated and isinstance(exc, (sa.exc.OperationalError, psycopg.OperationalError)):
        return "unavailable"
    return "other"


class Result:
    """A cursor-like result. Rows are plain dicts. Errors raised while fetching are translated."""

    def __init__(self, result: Any, translate: Callable[[Exception], NoReturn]) -> None:
        self._result = result
        self._translate = translate
        # Read now: the cursor closes once the statement is done, and a commit follows.
        self._rowcount = result.rowcount

    @property
    def rowcount(self) -> int:
        return self._rowcount

    def fetchone(self) -> dict[str, Any] | None:
        try:
            row = self._result.mappings().fetchone()
        except Exception as exc:
            self._translate(exc)
        return None if row is None else dict(row)

    def fetchall(self) -> list[dict[str, Any]]:
        try:
            rows = self._result.mappings().fetchall()
        except Exception as exc:
            self._translate(exc)
        return [dict(row) for row in rows]


class Connection:
    """One database connection for one request. Wraps a SQLAlchemy Connection."""

    def __init__(self, sa_connection: sa.Connection) -> None:
        self._conn = sa_connection

    @property
    def raw(self) -> Any:
        """The driver's own connection (sqlite3 or psycopg), for tests that break it on purpose."""
        return self._conn.connection.driver_connection

    def _unavailable(self, exc: Exception) -> DatabaseUnavailable:
        _log_unavailable(driver_error(exc))
        return DatabaseUnavailable("Database unavailable")

    def _translate(self, exc: Exception) -> NoReturn:
        driver = driver_error(exc)
        kind = classify_error(exc, bool(getattr(exc, "connection_invalidated", False)))
        # `from None` everywhere: SQLAlchemy's wrapper text is not carried into any traceback.
        if kind == "unavailable":
            raise self._unavailable(exc) from None
        if kind == "integrity":
            try:
                self.rollback()
            except Exception as rollback_exc:
                raise self._unavailable(rollback_exc) from None
            raise IntegrityViolation(str(driver)) from None
        raise driver from None

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> Result:
        try:
            return Result(self._conn.execute(sa.text(sql), params or {}), self._translate)
        except Exception as exc:
            self._translate(exc)

    def commit(self) -> None:
        try:
            self._conn.commit()
        except Exception as exc:
            self._translate(exc)

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def create_engine_for(target: SqliteTarget | PostgresTarget) -> sa.Engine:
    """Build an engine. It does not connect. NullPool: one connection per request (entry 23).

    hide_parameters keeps bound values out of SQLAlchemy's error text, as a second line of defence.
    """
    if isinstance(target, SqliteTarget):
        # mode=rw: fail if the file is missing, instead of creating an empty one.
        # check_same_thread=False: each request has its own connection, and that request's steps
        # run one after another, so no connection is used by two threads at the same time.
        url = sa.URL.create(
            "sqlite+pysqlite",
            database="file:" + quote(target.path.as_posix(), safe="/"),
            query={"mode": "rw", "uri": "true"},
        )
        engine = sa.create_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"check_same_thread": False},
        )

        @sa.event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

        return engine
    try:
        connect_args = config.postgres_connect_args(target.url)
    except Exception:
        # Startup validation already rejects such a URL. The driver's own error text can hold the
        # password, so it is dropped here too.
        raise config.ConfigError("DATABASE_URL is not a valid PostgreSQL URL") from None
    # The driver is named in the URL; host, user and password go in as libpq parameters.
    return sa.create_engine(
        "postgresql+psycopg://",
        poolclass=NullPool,
        hide_parameters=True,
        connect_args=connect_args,
    )


def open_connection(engine: sa.Engine) -> Connection:
    """Open a connection. Every failure here means 503 (entry 26), logged once without secrets."""
    try:
        return Connection(engine.connect())
    except Exception as exc:
        _log_unavailable(driver_error(exc))
        raise DatabaseUnavailable("Database unavailable") from None


def get_db(request: Request) -> Iterator[Connection]:
    conn = open_connection(request.app.state.engine)
    try:
        yield conn
    finally:
        conn.close()
