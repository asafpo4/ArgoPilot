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


def test_unencoded_at_in_password_fails_startup_without_leaking(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secHEAD@retTAIL@127.0.0.1:1/db")
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass
    only = "".join(traceback.format_exception_only(excinfo.value))
    assert excinfo.value.__cause__ is None
    for fragment in ("secHEAD", "retTAIL", "user", "127.0.0.1"):
        assert fragment not in only


@pytest.mark.parametrize(
    "url, fragments",
    [
        ("postgresql://user:2024/Secret@127.0.0.1:1/db", ["Secret", "2024", "user", "127.0.0.1"]),
        ("postgresql://svcuser.invalid:2024/Secret@db.example:5432/app", ["Secret", "2024", "svcuser", "db.example"]),
        ("postgresql://svcuser.invalid:/Secret@db.example/app", ["Secret", "svcuser", "db.example"]),
        ("postgresql://us.invalid/er:hunter2@127.0.0.1:1/app", ["hunter2", "us.invalid", "127.0.0.1"]),
        ("postgresql://user:12/SECRET@h1.invalid,127.0.0.1:1/db", ["SECRET", "h1.invalid", "127.0.0.1"]),
    ],
)
def test_misread_path_urls_fail_startup_without_leaking(monkeypatch, url, fragments):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass
    only = "".join(traceback.format_exception_only(excinfo.value))
    assert excinfo.value.__cause__ is None
    for fragment in fragments:
        assert fragment not in only


AFTER_AUTHORITY_URLS = [
    ("postgresql://svcuser.invalid:12/c?application_name=Secret@127.0.0.1:1/db", ["Secret", "svcuser", "12", "127.0.0.1"]),
    ("postgresql://svc.invalid/er:hunter2?application_name=x@127.0.0.1:1/db", ["hunter2", "svc.invalid", "127.0.0.1"]),
    ("postgresql://svcuser.invalid:12/cSEC?options=Secret@127.0.0.1:1/db", ["SEC", "Secret", "svcuser", "127.0.0.1"]),
    ("postgresql://svcuser.invalid:/cSEC?application_name=Secret@127.0.0.1:1/db", ["SEC", "Secret", "svcuser", "127.0.0.1"]),
    ("postgresql://svcuser.invalid:12/?application_name=Secret@127.0.0.1:1/db", ["Secret", "svcuser", "127.0.0.1"]),
    ("postgresql://svcuser.invalid:12/c?sslmode=x@127.0.0.1:1/db", ["svcuser", "127.0.0.1"]),
    ("postgresql://127.0.0.1:1/c?sslmode=Secret@x/db", ["Secret"]),
    ("postgresql://u:pw@h/db#frag@ment", ["frag", "ment"]),
]


@pytest.mark.parametrize("url, fragments", AFTER_AUTHORITY_URLS)
def test_at_after_the_authority_fails_startup_without_leaking(monkeypatch, url, fragments):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass
    only = "".join(traceback.format_exception_only(excinfo.value))
    assert excinfo.value.__cause__ is None
    for fragment in fragments:
        assert fragment not in only


@pytest.mark.parametrize("url, fragments", AFTER_AUTHORITY_URLS[:7])
def test_target_built_from_a_misread_url_prints_no_secret(url, fragments):
    t = config.PostgresTarget(url)
    for text in (repr(t), str(t)):
        for fragment in fragments:
            if fragment == "12":
                continue
            assert fragment not in text


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:pw@h/my%40db",
        "postgresql://u:pw@h/db?application_name=a%40b",
        "postgresql://u:pw@h/db?sslmode=require",
    ],
)
def test_encoded_at_and_plain_queries_are_still_accepted(url):
    assert isinstance(config.parse_database_url(url), config.PostgresTarget)
