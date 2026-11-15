"""PostgreSQL failure behavior: every test needs a real PostgreSQL (TEST_DATABASE_URL)."""

import logging
import os
import socket
import time
from collections.abc import Iterator
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

import db
import pg_support
from main import app

FARM_ID = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
WRONG_PASSWORD = "wrong-pw-unique-7431"


def assert_unavailable(response, retry_after: str = "5") -> None:
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["Retry-After"] == retry_after
    body = response.json()
    assert body["code"] == "UNAVAILABLE"
    assert body["detail"] == "Database unavailable"


def get_crops(url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", url)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get("/v1/crops")


def test_wrong_password_returns_503(pg_base_url, monkeypatch):
    url = pg_support.with_url_parts(pg_base_url, password=WRONG_PASSWORD)
    assert_unavailable(get_crops(url, monkeypatch))


def test_unknown_database_returns_503(pg_base_url, monkeypatch):
    url = pg_support.with_url_parts(pg_base_url, dbname="no_such_db_7431")
    assert_unavailable(get_crops(url, monkeypatch))


def test_unreachable_server_returns_503(pg_base_url, monkeypatch):
    url = pg_support.with_url_parts(pg_base_url, port=1)
    assert_unavailable(get_crops(url, monkeypatch))


def test_row_lock_returns_503_within_lock_timeout(pg_app_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_app_url)
    other = psycopg.connect(pg_app_url)
    try:
        other.execute("UPDATE farms SET name = name WHERE id = %s", (FARM_ID,))
        with TestClient(app, raise_server_exceptions=False) as client:
            start = time.monotonic()
            response = client.patch(f"/v1/farms/{FARM_ID}", json={"name": "Locked out"})
            elapsed = time.monotonic() - start
        assert_unavailable(response)
        assert 4.5 <= elapsed <= 9
    finally:
        other.rollback()
        other.close()


@pytest.fixture
def override_cleanup() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(db.get_db, None)


def test_cut_socket_returns_503(pg_app_url, monkeypatch, override_cleanup):
    monkeypatch.setenv("DATABASE_URL", pg_app_url)

    def cut_socket_db() -> Iterator[db.Connection]:
        conn = db.connect_postgres(pg_app_url)
        try:
            conn.execute("SELECT 1")
            socket.socket(fileno=os.dup(conn.raw.fileno())).shutdown(socket.SHUT_RDWR)
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[db.get_db] = cut_socket_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/crops")
    assert_unavailable(response)


def test_terminated_backend_returns_503(pg_app_url, monkeypatch, override_cleanup):
    monkeypatch.setenv("DATABASE_URL", pg_app_url)

    def terminated_db() -> Iterator[db.Connection]:
        conn = db.connect_postgres(pg_app_url)
        try:
            conn.execute("SELECT 1")
            pid = conn.raw.info.backend_pid
            with psycopg.connect(pg_app_url, autocommit=True) as other:
                other.execute("SELECT pg_terminate_backend(%s)", (pid,))
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[db.get_db] = terminated_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/crops")
    assert_unavailable(response)


def test_failure_log_has_cause_and_no_password(pg_base_url, monkeypatch, caplog):
    url = pg_support.with_url_parts(pg_base_url, password=WRONG_PASSWORD)
    real_password = urlsplit(pg_base_url).password
    with caplog.at_level(logging.WARNING, logger="registry.db"):
        assert_unavailable(get_crops(url, monkeypatch))
    records = [
        r
        for r in caplog.records
        if r.name == "registry.db" and r.levelno == logging.WARNING
    ]
    assert len(records) == 1
    assert "password authentication failed" in records[0].getMessage()
    assert WRONG_PASSWORD not in caplog.text
    assert real_password and real_password not in caplog.text
