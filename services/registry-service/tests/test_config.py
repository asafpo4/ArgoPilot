import traceback
from pathlib import Path

import pydantic
import pytest

import config
from fakes import exception_chain
from config import (
    DEFAULT_SQLITE_PATH,
    SERVICE_DIR,
    ConfigError,
    PostgresTarget,
    SqliteTarget,
    load_settings,
    parse_database_url,
    postgres_connect_args,
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


PG_URL = "postgresql://registry:pw@db.internal:5432/registry"


def test_settings_read_dot_env_when_no_real_variable(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite:///x.db\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_settings(env_file).target == SqliteTarget(SERVICE_DIR / "x.db")


def test_real_variable_beats_dot_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={PG_URL}\n")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///a.db")
    assert load_settings(env_file).target == SqliteTarget(SERVICE_DIR / "a.db")


def test_empty_real_variable_beats_dot_env_and_means_default_sqlite(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={PG_URL}\n")
    monkeypatch.setenv("DATABASE_URL", "")
    assert load_settings(env_file).target == SqliteTarget(DEFAULT_SQLITE_PATH)


def test_other_keys_in_dot_env_are_ignored(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DATABASE_URL=postgresql://x@h/t\nFOO=1\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert load_settings(env_file).target == SqliteTarget(DEFAULT_SQLITE_PATH)


def test_invalid_value_raises_config_error_without_the_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:s3cret@h:99999/db")
    with pytest.raises(ConfigError) as info:
        load_settings(Path("/nonexistent/.env"))
    assert "s3cret" not in str(info.value)
    assert "s3cret" not in "".join(traceback.format_exception(info.value))


def test_connect_args_set_timeouts_and_append_to_existing_options():
    args = postgres_connect_args("postgresql://u@h/db?options=-csearch_path%3Dx")
    assert args["connect_timeout"] == 5
    assert args["options"] == "-csearch_path=x -c lock_timeout=5000"


def test_connect_args_without_options_set_only_the_lock_timeout():
    args = postgres_connect_args("postgresql://u@h/db")
    assert args["options"] == "-c lock_timeout=5000"


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


@pytest.mark.parametrize(
    "url, fragments",
    [
        ("postgresql://admin:123456", ["admin", "123456"]),
        ("postgresql://admin.invalid:123456/appdb", ["admin", "123456", "appdb"]),
        ("postgresql://u:pw@h:70000/db", ["70000", "pw"]),
        ("postgresql://u:pw@h:0/db", ["pw"]),
    ],
)
def test_ports_outside_1_to_65535_are_rejected_without_leaking(url, fragments):
    _assert_fixed_error(url, fragments)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:pw@h:65535/db",
        "postgresql://u:pw@h:05432/db",
        "postgresql://u:pw@h1:1,h2:2/db",
        "postgresql://u:pw@h1,h2:5/db",
        "postgresql://u:pw@h1:,h2:5/db",
    ],
)
def test_ports_in_range_are_accepted(url):
    assert isinstance(parse_database_url(url), PostgresTarget)


def test_same_database_cannot_read_a_port_that_is_not_plain_digits():
    assert not same_database("postgresql://u@localhost:+5432/registry", "postgresql://u@localhost/registry")
    assert not same_database("postgresql://u@localhost/registry?port=%205432", "postgresql://u@localhost/registry")
    assert same_database("postgresql://u@localhost:05432/registry", "postgresql://u@localhost/registry")


def test_settings_repr_and_str_never_show_the_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:PWMARKER9z@db.internal:5432/registry")
    settings = load_settings(Path("/nonexistent/.env"))
    assert settings.DATABASE_URL  # The value is there, so a leak in repr or str would show.
    assert "Settings" in repr(settings)
    for text in (repr(settings), str(settings)):
        assert "PWMARKER9z" not in text
        assert "db.internal" not in text


# Each URL below reaches a different place that raises ConfigError.
CONFIG_ERROR_URLS = [
    "postgresql://u:PWMARKER9z\u2100@127.0.0.1:1/db",  # urlsplit rejects it (NFKC), ValueError
    "postgresql://u:PWMARKER9z%zz@127.0.0.1:1/db",  # libpq cannot read it
    "mysql://u:PWMARKER9z@h/db",  # unsupported scheme
    "sqlite://u:PWMARKER9z@h/x.db",  # sqlite with a host part
]


@pytest.mark.parametrize("url", CONFIG_ERROR_URLS)
def test_config_error_chain_has_no_context_and_no_secret(url):
    with pytest.raises(ConfigError) as info:
        parse_database_url(url)
    assert exception_chain(info.value) == [info.value]
    assert info.value.__context__ is None
    assert "PWMARKER9z" not in str(info.value)
    assert "PWMARKER9z" not in "".join(traceback.format_exception(info.value))


@pytest.mark.parametrize("url", CONFIG_ERROR_URLS)
def test_startup_settings_error_chain_has_no_context_and_no_secret(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigError) as info:
        load_settings(Path("/nonexistent/.env"))
    assert exception_chain(info.value) == [info.value]
    assert "PWMARKER9z" not in "".join(traceback.format_exception(info.value))


# Remaining lines and branches of config.py, one test per behaviour.


def test_repr_of_a_url_libpq_cannot_parse_shows_nothing():
    secret_url = "postgresql://u:secr%zzet@127.0.0.1:1/db"
    target = PostgresTarget(secret_url)
    assert str(target) == "postgresql://***"
    assert repr(target) == "PostgresTarget(url='postgresql://***')"


def test_repr_puts_an_ipv6_host_in_brackets():
    assert str(PostgresTarget("postgresql://u:pw@[::1]/db")) == "postgresql://u:***@[::1]/db"


def test_repr_masks_a_password_that_has_no_user():
    assert str(PostgresTarget("postgresql://:pw@h/db")) == "postgresql://:***@h/db"


def test_repr_shows_nothing_when_the_database_name_holds_part_of_a_password(monkeypatch):
    # libpq reads this URL's database name as "Secret@127.0.0.1:1/db". The consistency check
    # normally rejects it first, so it is switched off to reach the name check.
    monkeypatch.setattr(config, "_libpq_agrees_with_urlsplit", lambda url: True)
    target = PostgresTarget("postgresql://user:2024/Secret@127.0.0.1:1/db")
    assert str(target) == "postgresql://***"
    assert repr(target) == "PostgresTarget(url='postgresql://***')"


def test_load_settings_turns_a_pydantic_validation_error_into_a_config_error(monkeypatch):
    class Strict(pydantic.BaseModel):
        value: int

    def failing_settings(**kwargs):
        Strict(value="SECRET-VALUE")  # raises a real ValidationError that holds the input

    monkeypatch.setattr(config, "Settings", failing_settings)
    with pytest.raises(ConfigError) as info:
        load_settings(Path("/nonexistent/.env"))
    assert str(info.value) == "Invalid settings"
    assert exception_chain(info.value) == [info.value]
    assert "SECRET-VALUE" not in "".join(traceback.format_exception(info.value))


def test_port_list_shorter_than_the_host_list_is_rejected():
    # Two hosts from ?host=, one port in the netloc: libpq counts 2 ports, the netloc has 1.
    _assert_fixed_error("postgresql://:1/db?host=a,b&port=1,2", ["a,b", "1,2"])


def test_query_port_that_differs_from_the_netloc_port_is_rejected():
    _assert_fixed_error("postgresql://u@h:5432/db?port=5433", ["5433"])


def test_more_ports_than_hosts_is_rejected():
    _assert_fixed_error("postgresql://u@h/db?port=1,2", ["1,2"])
