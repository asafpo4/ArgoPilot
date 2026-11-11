import os
from pathlib import Path

import pytest

from config import (
    DEFAULT_SQLITE_PATH,
    ConfigError,
    PostgresTarget,
    SqliteTarget,
    load_environment,
    parse_database_url,
    same_database,
)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_empty_and_whitespace_use_default_sqlite(value):
    assert parse_database_url(value) == SqliteTarget(DEFAULT_SQLITE_PATH)


def test_relative_sqlite_path_resolves_against_base_dir(tmp_path):
    assert parse_database_url("sqlite:///x.db", tmp_path) == SqliteTarget(tmp_path / "x.db")
    assert parse_database_url("sqlite:////abs/y.db", tmp_path) == SqliteTarget(
        Path("/abs/y.db")
    )


@pytest.mark.parametrize("value", ["sqlite://", "sqlite:///"])
def test_sqlite_url_without_path_is_an_error(value):
    with pytest.raises(ConfigError):
        parse_database_url(value)


@pytest.mark.parametrize(
    "value", ["postgres://u:p@h/db", "postgresql://u:p@h/db", "POSTGRESQL://u:p@h/db"]
)
def test_both_postgres_schemes_and_any_case(value):
    target = parse_database_url(value)
    assert isinstance(target, PostgresTarget)
    assert target.url.startswith("postgresql://")


@pytest.mark.parametrize("value", ["mysql://u:s3cret@h/db", "not a url s3cret"])
def test_unknown_or_malformed_url_raises_without_secret(value):
    with pytest.raises(ConfigError) as exc:
        parse_database_url(value)
    assert "s3cret" not in str(exc.value)


def test_password_with_special_characters_is_redacted():
    t = parse_database_url("postgresql://u:p%40ss%3Aw%2Frd@h/db")
    for text in (repr(t), str(t)):
        for secret in ("p@ss", "p%40ss", "w/rd"):
            assert secret not in text
        assert "***" in text


def test_same_database_rules():
    base = "postgresql://u:p@localhost:5432/reg"
    assert same_database(base, "postgres://x:y@localhost/reg")
    assert same_database("postgresql://h/reg", "postgresql://h:5432/reg")
    assert same_database("postgresql://localhost/reg", "postgresql://127.0.0.1/reg")
    assert same_database("postgresql://localhost/reg", "postgresql://[::1]/reg")
    assert not same_database(base, "postgresql://localhost:5432/other")
    assert not same_database(base, "postgresql://otherhost:5432/reg")
    assert not same_database(base, "postgresql://localhost:5433/reg")
    assert not same_database(None, base)
    assert not same_database(base, None)
    assert not same_database("sqlite:///a.db", "sqlite:///a.db")
    assert not same_database("sqlite:///a.db", base)


def test_load_environment_fills_missing_but_never_overrides(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CFG_TEST_A=1\nCFG_TEST_B=2\n")
    monkeypatch.delenv("CFG_TEST_A", raising=False)
    monkeypatch.setenv("CFG_TEST_B", "keep")
    load_environment(env_file)
    try:
        assert os.environ["CFG_TEST_A"] == "1"
        assert os.environ["CFG_TEST_B"] == "keep"
    finally:
        os.environ.pop("CFG_TEST_A", None)
