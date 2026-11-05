import sqlite3
from collections.abc import Iterator
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "registry.db"


def connect(path: Path) -> sqlite3.Connection:
    # mode=rw: fail if the file is missing, instead of creating an empty one.
    # check_same_thread=False: each request has its own connection, and that request's steps
    # run one after another, so no connection is used by two threads at the same time.
    conn = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()
