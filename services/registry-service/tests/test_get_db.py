"""get_db must close the request's connection, also when the route raises.

With NullPool nothing else ends a connection: a missed close leaves a PostgreSQL backend open
and idle in a transaction, which holds locks until the server is stopped.
"""

from types import SimpleNamespace

import pytest

import db
from fakes import FakeSAConnection


class StubEngine:
    def __init__(self) -> None:
        self.connection = FakeSAConnection()

    def connect(self) -> FakeSAConnection:
        return self.connection


def make_request(engine: StubEngine) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))


def test_get_db_closes_the_connection_when_the_route_finishes() -> None:
    engine = StubEngine()
    generator = db.get_db(make_request(engine))
    conn = next(generator)
    assert isinstance(conn, db.Connection)
    assert engine.connection.closes == 0  # Still open while the route runs.
    with pytest.raises(StopIteration):
        next(generator)
    assert engine.connection.closes == 1


def test_get_db_closes_the_connection_when_the_route_raises() -> None:
    engine = StubEngine()
    generator = db.get_db(make_request(engine))
    next(generator)
    with pytest.raises(RuntimeError, match="route failed"):
        generator.throw(RuntimeError("route failed"))
    assert engine.connection.closes == 1
