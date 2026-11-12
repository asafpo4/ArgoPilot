import traceback

import pytest
from fastapi.testclient import TestClient

import config
from config import ConfigError, SqliteTarget
from main import app

CLOSED_PORT_POSTGRES = "postgresql://postgres:x@127.0.0.1:1/registry"


def test_startup_stores_parsed_target_on_app_state():
    with TestClient(app):
        assert isinstance(app.state.db_target, SqliteTarget)


def test_each_startup_parses_again(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "a.db"))
    with TestClient(app):
        first = app.state.db_target
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "b.db"))
    with TestClient(app):
        second = app.state.db_target
    assert first != second


def test_unknown_scheme_fails_startup_without_leaking_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://u:s3cret@h/db")
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass
    assert "s3cret" not in str(excinfo.value)
    assert "mysql://u:s3cret@h/db" not in str(excinfo.value)
    assert "mysql://" not in str(excinfo.value)


def test_bad_dot_env_does_not_affect_default_run(client, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=nonsense://x\n")
    config.load_environment(env_file)
    with TestClient(app) as second:
        assert second.get("/v1/crops").status_code == 200


def test_postgres_dot_env_does_not_affect_default_run(client, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={CLOSED_PORT_POSTGRES}\n")
    config.load_environment(env_file)
    with TestClient(app) as second:
        assert second.get("/v1/crops").status_code == 200


# Only meaningful on the SQLite get_db override; PostgreSQL uses the real get_db.
@pytest.mark.parametrize("database", ["sqlite"], indirect=True)
def test_postgres_url_in_environment_keeps_default_fixtures_on_sqlite(monkeypatch, client):
    monkeypatch.setenv("DATABASE_URL", CLOSED_PORT_POSTGRES)
    with TestClient(app) as fresh:
        # The PostgreSQL URL reached startup and was parsed without connecting.
        assert isinstance(app.state.db_target, config.PostgresTarget)
        # The client fixture's SQLite override still serves requests from the temp copy.
        response = fresh.get("/v1/crops")
        assert response.status_code == 200
        assert response.json()


def test_unparsable_postgres_url_fails_startup_without_leaking(monkeypatch):
    url = "postgresql://u:secr%zzet@127.0.0.1:1/db"
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass
    formatted = "".join(traceback.format_exception(excinfo.value))
    for text in (str(excinfo.value), formatted.split("ConfigError", 1)[-1]):
        assert "secr" not in text
        assert "zzet" not in text
        assert url not in text
    assert url not in formatted
