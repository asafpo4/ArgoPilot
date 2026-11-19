"""Settings: the table of spec 5.3, the defaults, the .env rules, and that no value ever reaches an error or a repr."""

import re
import shutil
import traceback
from pathlib import Path

import pytest

import config
from config import ConfigError, Settings, load_settings

SERVICE_DIR = Path(__file__).resolve().parent.parent
BASE = "https://api.open-meteo.com/v1/forecast"
NO_FILE = Path("/nonexistent/.env")
URL = "PROVIDER_BASE_URL"
KEY = "PROVIDER_API_KEY"
TIMEOUT = "PROVIDER_TIMEOUT_SECONDS"
RETRIES = "PROVIDER_RETRIES"
DELAY = "PROVIDER_RETRY_DELAY_SECONDS"
FRESH = "FRESH_FOR_SECONDS"
STALE = "STALE_MAX_AGE_SECONDS"
COOLDOWN = "COOLDOWN_SECONDS"
CACHE = "CACHE_MAX_CELLS"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's real variables must not change what these tests see.
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


def load(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return load_settings(NO_FILE)


def chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    todo = [exc]
    while todo:
        current = todo.pop()
        if any(current is known for known in seen):
            continue
        seen.append(current)
        todo += [e for e in (current.__cause__, current.__context__) if e is not None]
    return seen


# One row per case of the Settings table in spec 5.3: (variable that must be named, environment).
ACCEPTED = [
    (URL, {URL: BASE}),
    (URL, {URL: "http://localhost:9000/v1/forecast"}),
    (URL, {URL: "http://example.com/x"}),
    (URL, {URL: "https://example.com/x", KEY: "k"}),
    (URL, {URL: "http://127.0.0.1:9000/x", KEY: "k"}),
    (URL, {URL: "http://localhost/x", KEY: "k"}),
    (URL, {URL: "http://[::1]:9000/x", KEY: "k"}),
    (URL, {URL: "HTTP://LOCALHOST:9000/x", KEY: "k"}),
    (URL, {URL: "http://example.com/x", KEY: ""}),
    (URL, {URL: "http://example.com/x", KEY: "   "}),
    *[(TIMEOUT, {TIMEOUT: v}) for v in ("0.1", "3", "30")],
    *[(RETRIES, {RETRIES: v}) for v in ("0", "2", "5")],
    *[(DELAY, {DELAY: v}) for v in ("0", "0.5", "10")],
    *[(FRESH, {FRESH: v}) for v in ("1", "10800")],
    (STALE, {STALE: "10800"}),  # equal to the default FRESH_FOR_SECONDS
    (STALE, {STALE: "86400"}),
    *[(COOLDOWN, {COOLDOWN: v}) for v in ("0", "30")],
    *[(CACHE, {CACHE: v}) for v in ("1", "2000")],
]

REJECTED = [
    (URL, {}),  # missing
    *[(URL, {URL: v}) for v in ("", "ftp://example.com/x", "example.com/x", "https://")],
    *[
        (URL, {URL: v, KEY: "k"})
        for v in (
            "http://example.com/x",
            "http://localhost.example.com/x",
            "http://127.0.0.1.example.com/x",
            "http://localhost@example.com/x",
            "http://example.com/x#@localhost",
            "http://192.168.1.5/x",
        )
    ],
    *[(TIMEOUT, {TIMEOUT: v}) for v in ("0", "-1", "30.1", "31", "abc", "nan", "inf", "")],
    *[(RETRIES, {RETRIES: v}) for v in ("-1", "6", "1.5", "abc", "")],
    *[(DELAY, {DELAY: v}) for v in ("-0.1", "10.1", "abc", "nan", "")],
    *[(FRESH, {FRESH: v}) for v in ("0", "-5", "abc", "nan", "inf", "")],
    (STALE, {STALE: "100"}),  # smaller than the default FRESH_FOR_SECONDS
    *[(STALE, {STALE: v}) for v in ("abc", "nan", "inf", "")],
    *[(COOLDOWN, {COOLDOWN: v}) for v in ("-1", "abc", "nan", "inf", "")],
    *[(CACHE, {CACHE: v}) for v in ("0", "-1", "1.5", "abc", "")],
]


@pytest.mark.parametrize("variable, env", ACCEPTED)
def test_accepted_values_load(monkeypatch: pytest.MonkeyPatch, variable: str, env: dict[str, str]) -> None:
    settings = load(monkeypatch, {URL: BASE, **env})
    if variable != URL:
        assert getattr(settings, variable) == float(env[variable])
    assert settings.api_key() == env.get(KEY, "").strip()


@pytest.mark.parametrize("variable, env", REJECTED)
def test_rejected_values_stop_startup_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, variable: str, env: dict[str, str]
) -> None:
    base = {} if variable == URL and URL not in env else {URL: BASE}
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {**base, **env})
    assert f"{variable}: " in str(info.value)  # named as a problem, not only mentioned in a rule text
    assert chain(info.value) == [info.value]  # no driver or pydantic error stays in the chain


def test_defaults_equal_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(monkeypatch, {URL: BASE})
    assert settings.PROVIDER_BASE_URL == BASE
    assert settings.api_key() == ""
    assert settings.PROVIDER_TIMEOUT_SECONDS == 3
    assert settings.PROVIDER_RETRIES == 2
    assert settings.PROVIDER_RETRY_DELAY_SECONDS == 0.5
    assert settings.FRESH_FOR_SECONDS == 10800
    assert settings.STALE_MAX_AGE_SECONDS == 86400
    assert settings.COOLDOWN_SECONDS == 30
    assert settings.CACHE_MAX_CELLS == 2000


def test_missing_base_url_error_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {})
    assert "PROVIDER_BASE_URL: required" in str(info.value)


def test_every_bad_variable_is_named_in_one_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {URL: BASE, TIMEOUT: "0", CACHE: "0"})
    assert f"{TIMEOUT}: " in str(info.value) and f"{CACHE}: " in str(info.value)


# The .env file and the environment.


def test_dot_env_is_read_next_to_config_py_not_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service, elsewhere = tmp_path / "service", tmp_path / "cwd"
    service.mkdir()
    elsewhere.mkdir()
    (service / ".env").write_text("PROVIDER_BASE_URL=https://from-service-dir.example.com/x\n")
    (elsewhere / ".env").write_text("PROVIDER_BASE_URL=https://from-cwd.example.com/x\n")
    monkeypatch.setattr(config, "SERVICE_DIR", service)
    monkeypatch.chdir(elsewhere)
    assert load_settings().PROVIDER_BASE_URL == "https://from-service-dir.example.com/x"


def test_a_real_variable_beats_dot_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{URL}={BASE}\n{TIMEOUT}=5\n")
    monkeypatch.setenv(TIMEOUT, "7")
    assert load_settings(env_file).PROVIDER_TIMEOUT_SECONDS == 7


def test_an_empty_real_variable_beats_dot_env_for_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # .env has a key with an http URL, which alone would be refused. The empty real variable wins.
    env_file = tmp_path / ".env"
    env_file.write_text(f"{URL}=http://example.com/x\n{KEY}=from-dot-env\n")
    monkeypatch.setenv(KEY, "")
    assert load_settings(env_file).api_key() == ""


def test_an_empty_real_number_variable_is_invalid_and_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{URL}={BASE}\n{TIMEOUT}=5\n")
    monkeypatch.setenv(TIMEOUT, "")
    with pytest.raises(ConfigError) as info:
        load_settings(env_file)
    assert TIMEOUT in str(info.value)


def test_other_keys_in_dot_env_are_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{URL}={BASE}\nSOMETHING_ELSE=1\n")
    assert load_settings(env_file).PROVIDER_BASE_URL == BASE


# Secrets: no value reaches a repr, a message, a traceback, or the exception chain.

LEAK = "LEAKMARK"
LEAKY = [
    (URL, {URL: f"ftp://user:{LEAK}pw@host/x"}),
    (URL, {URL: f"http://example.com/x?token={LEAK}url", KEY: f"{LEAK}key"}),
    (TIMEOUT, {TIMEOUT: f"3{LEAK}"}),
    (RETRIES, {RETRIES: f"2{LEAK}"}),
    (DELAY, {DELAY: f"1{LEAK}"}),
    (FRESH, {FRESH: f"1{LEAK}"}),
    (STALE, {STALE: f"1{LEAK}"}),
    (COOLDOWN, {COOLDOWN: f"1{LEAK}"}),
    (CACHE, {CACHE: f"1{LEAK}"}),
]


@pytest.mark.parametrize("variable, env", LEAKY)
def test_a_rejected_value_is_never_in_the_error(
    monkeypatch: pytest.MonkeyPatch, variable: str, env: dict[str, str]
) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {URL: BASE, **env})
    assert f"{variable}: " in str(info.value)
    assert LEAK not in str(info.value)
    assert LEAK not in "".join(traceback.format_exception(info.value))
    assert all(LEAK not in str(e) for e in chain(info.value))


def test_repr_and_str_never_show_the_key_or_the_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(
        monkeypatch,
        {URL: "https://secret-host.example.com/path?x=URLMARKER", KEY: "KEYMARKER-123"},
    )
    assert "PROVIDER_TIMEOUT_SECONDS=3.0" in repr(settings)  # the repr exists and shows other fields
    for text in (repr(settings), str(settings)):
        assert "KEYMARKER-123" not in text
        assert "secret-host" not in text
        assert "URLMARKER" not in text


# .env.example


def example_variables() -> set[str]:
    text = (SERVICE_DIR / ".env.example").read_text()
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_every_setting_is_in_env_example_and_the_other_way_round() -> None:
    assert example_variables() == set(Settings.model_fields)


def test_env_example_loads_with_the_documented_defaults(tmp_path: Path) -> None:
    copy = tmp_path / ".env"
    shutil.copy(SERVICE_DIR / ".env.example", copy)
    settings = load_settings(copy)
    assert settings.api_key() == ""
    assert settings.PROVIDER_TIMEOUT_SECONDS == 3
    assert settings.PROVIDER_RETRIES == 2
    assert settings.PROVIDER_RETRY_DELAY_SECONDS == 0.5
    assert settings.FRESH_FOR_SECONDS == 10800
    assert settings.STALE_MAX_AGE_SECONDS == 86400
    assert settings.COOLDOWN_SECONDS == 30
    assert settings.CACHE_MAX_CELLS == 2000
