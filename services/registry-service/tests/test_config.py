import os
import traceback
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


@pytest.mark.parametrize(
    "url, fragments",
    [
        ("postgresql://u:secr%zzet@127.0.0.1:1/db", ["secr", "zzet", "u:", "127.0.0.1"]),
        ("postgresql://us%zzer:pw@h/db", ["us", "zzer", "pw", "h/db"]),
        ("postgresql://u:pw@h/d%zzb", ["pw", "zzb", "u:", "h/d"]),
    ],
)
def test_postgres_url_libpq_cannot_parse_is_an_error_without_leaking(url, fragments):
    with pytest.raises(ConfigError) as excinfo:
        parse_database_url(url)
    shown = str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.value))
    assert url not in shown
    assert url not in formatted
    for fragment in fragments:
        assert fragment not in shown
    for fragment in fragments:
        if fragment in ("us", "h/db", "h/d"):
            continue  # too short to be distinctive against the source lines shown in a traceback
        assert fragment not in formatted.split("ConfigError", 1)[-1]


FIXED_MESSAGE = "DATABASE_URL is not a valid PostgreSQL URL"


def _assert_fixed_error(url, fragments):
    with pytest.raises(ConfigError) as excinfo:
        parse_database_url(url)
    exc = excinfo.value
    assert str(exc) == FIXED_MESSAGE
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    only = "".join(traceback.format_exception_only(exc))
    for fragment in fragments:
        assert fragment not in only


def test_unencoded_at_in_password_is_rejected_without_leaking():
    _assert_fixed_error(
        "postgresql://user:secHEAD@retTAIL@127.0.0.1:1/db",
        ["secHEAD", "retTAIL", "user", "127.0.0.1"],
    )


def test_unencoded_slash_in_password_is_rejected_without_leaking():
    _assert_fixed_error("postgresql://user:pa/SECRET@h/db", ["pa/", "SECRET", "user"])


def test_non_numeric_port_is_rejected_without_echoing_it():
    _assert_fixed_error("postgresql://u:pw@h:notaport/db", ["notaport"])


def test_query_parameters_conflicting_with_the_netloc_are_rejected():
    _assert_fixed_error(
        "postgresql://u@placeholder/x?host=h2&port=5433&dbname=real", ["placeholder", "real"]
    )
    _assert_fixed_error("postgresql://u:pw@h/db?user=other", ["other"])
    _assert_fixed_error("postgresql://u:pw@h/db?password=other", ["other"])


@pytest.mark.parametrize(
    "url",
    [
        "postgresql:///db?host=/var/run/postgresql",
        "postgresql://u:pw@h:5432/db?sslmode=require",
        "postgresql://u:@h/db",
        "postgresql://u:pw@[::1]/db",
        "postgresql://u:pw@[::1]:5433/db",
        "postgresql://h",
        "postgresql://u:pw@h/",
        "postgresql://h1,h2/db",
        "postgresql://u:pw@h1:1,h2:2/db",
        "postgresql://u:pw@h/db?options=-csearch_path%3Dtest_x&sslmode=require",
        "postgres://u:p%40ss%3Aw%2Frd@H/db",
        "postgresql://us%40er:pw@h/d%20b",
    ],
)
def test_valid_postgres_urls_are_accepted(url):
    target = parse_database_url(url)
    assert isinstance(target, PostgresTarget)
    assert target.url == "postgresql" + url[url.index("://"):]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p%2Fq%23r%3Fs%40t%3Au@h/db",
        "postgresql://u:p%2Fq%23r%3Fs%40t%3Au@h:5433/db?sslmode=require&application_name=zzz",
    ],
)
def test_repr_and_str_show_no_password_and_no_query(url):
    target = parse_database_url(url)
    _assert_redacted(target)


@pytest.mark.parametrize("url", ["postgresql://u:p#x@h/db", "postgresql://u:p?x@h/db"])
def test_repr_hides_a_password_urlsplit_would_misread(url):
    # libpq accepts these, startup rejects them; the display must still be safe.
    _assert_redacted(PostgresTarget(url))


def _assert_redacted(target):
    for text in (repr(target), str(target)):
        for secret in ("p/q", "p%2Fq", "q#r", "%23", "s?t", "s@t", "t:u", "zzz", "p#x", "p?x"):
            assert secret not in text
        assert "***" in text
        assert "?" not in text
        assert "sslmode" not in text


def test_repr_shape_for_a_simple_url():
    t = parse_database_url("postgres://u:pw@h:5433/db?sslmode=require")
    assert str(t) == "postgresql://u:***@h:5433/db"
    assert repr(t) == "PostgresTarget(url='postgresql://u:***@h:5433/db')"
    assert str(parse_database_url("postgresql://h/db")) == "postgresql://h/db"


def test_same_database_follows_libpq_defaults_and_overrides():
    assert same_database("postgresql://registry@db", "postgresql://registry@db/registry")
    assert same_database(
        "postgresql://u@placeholder/x?host=H&port=5433&dbname=real", "postgresql://u@H:5433/real"
    )
    assert not same_database(
        "postgresql://u@placeholder/x?host=H&port=5433&dbname=real", "postgresql://u@H:5433/x"
    )
    assert not same_database("postgresql://registry@db", "postgresql://registry@db/other")
    assert same_database("postgresql://u@h/d%62", "postgresql://u@h/db")


def test_same_database_returns_false_for_urls_libpq_cannot_parse():
    good = "postgresql://u:pw@h/db"
    assert not same_database("postgresql://u:secr%zzet@h/db", good)
    assert not same_database(good, "postgresql://u:secr%zzet@h/db")


LEAK_URLS = [
    ("postgresql://user:2024/Secret@127.0.0.1:1/db", ["Secret", "2024", "user", "127.0.0.1"]),
    ("postgresql://svcuser.invalid:2024/Secret@db.example:5432/app", ["Secret", "2024", "svcuser", "db.example"]),
    ("postgresql://svcuser.invalid:/Secret@db.example/app", ["Secret", "svcuser", "db.example"]),
    ("postgresql://us.invalid/er:hunter2@127.0.0.1:1/app", ["hunter2", "us.invalid", "127.0.0.1"]),
    ("postgresql://user:12/SECRET@h1.invalid,127.0.0.1:1/db", ["SECRET", "h1.invalid", "127.0.0.1"]),
]


@pytest.mark.parametrize("url, fragments", LEAK_URLS)
def test_unencoded_at_in_the_path_is_rejected_without_leaking(url, fragments):
    _assert_fixed_error(url, fragments)


def test_repr_of_a_target_built_from_a_misread_url_never_shows_the_database_name():
    t = PostgresTarget("postgresql://user:2024/Secret@127.0.0.1:1/db")
    for text in (repr(t), str(t)):
        assert "Secret" not in text
        assert "127.0.0.1" not in text


def test_encoded_at_in_database_name_is_accepted():
    assert isinstance(parse_database_url("postgresql://u:pw@h/my%40db"), PostgresTarget)


def test_multi_host_skip_keys_on_the_netloc_not_on_libpq():
    _assert_fixed_error("postgresql://u:pw@h1,h2/db?host=x,y", ["h1", "x,y"])
    _assert_fixed_error("postgresql://u@placeholder/db?host=a,b", ["placeholder", "a,b"])
    parse_database_url("postgresql://u:pw@h1:1,h2:2/db")
    parse_database_url("postgresql://h1,h2:1/db")


def test_same_database_unknown_name_matches_any_name_on_same_host_and_port():
    assert same_database("postgresql://localhost", "postgresql://asaf@localhost")
    assert same_database("postgresql://localhost", "postgresql://localhost/other")
    assert same_database("postgresql://localhost/other", "postgresql://localhost")
    assert not same_database("postgresql://u@localhost/a", "postgresql://u@localhost/b")
    assert not same_database("postgresql://localhost", "postgresql://otherhost/other")


def test_leading_zero_port_is_accepted():
    assert isinstance(parse_database_url("postgresql://u@h:05432/db"), PostgresTarget)
    assert same_database("postgresql://u@h:05432/db", "postgresql://u@h/db")
