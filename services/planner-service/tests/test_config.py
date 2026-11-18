"""Settings: the table of spec 5.3, the defaults, the .env rules, and that no value ever reaches an error or a repr."""

import re
import shutil
import traceback
from pathlib import Path

import pytest

import config
from config import ConfigError, Settings, load_settings

SERVICE_DIR = Path(__file__).resolve().parent.parent
NO_FILE = "/nonexistent/.env"
REG = "REGISTRY_BASE_URL"
WEA = "WEATHER_BASE_URL"
REG_T = "REGISTRY_TIMEOUT_SECONDS"
REG_R = "REGISTRY_RETRIES"
WEA_T = "WEATHER_TIMEOUT_SECONDS"
WEA_R = "WEATHER_RETRIES"
DELAY = "RETRY_DELAY_SECONDS"
GOOD = {REG: "http://127.0.0.1:8000", WEA: "http://127.0.0.1:8001"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's real variables must not change what these tests see.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


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


URL_ACCEPTED = [
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("https://example.com/api", "https://example.com/api"),
    ("http://localhost:8001/", "http://localhost:8001"),  # the trailing "/" is removed
    ("http://localhost:8001//", "http://localhost:8001/"),  # only one "/" is removed
]
URL_REJECTED = [
    "",
    "ftp://example.com",
    "example.com",
    "https://",
    "http://user:pw@example.com",
    "http://user@example.com",
    "http://example.com/x?a=1",
    "http://example.com/x?",
    "http://example.com/x#f",
    "http://example.com/x#",
    "http://example.com:abc/x",
]
# (variable, accepted values, rejected values)
NUMBERS = [
    (REG_T, ["0.1", "2", "30"], ["0", "-1", "30.1", "abc", "nan", "inf", ""]),
    (REG_R, ["0", "1", "5"], ["-1", "6", "1.5", "abc", ""]),
    (WEA_T, ["0.1", "12", "240"], ["0", "-1", "240.1", "abc", "nan", "inf", ""]),
    (WEA_R, ["0", "1", "5"], ["-1", "6", "1.5", "abc", ""]),
    (DELAY, ["0", "0.3", "10"], ["-0.1", "10.1", "abc", "nan", ""]),
]
NUMBER_ACCEPTED = [(name, v) for name, ok, _ in NUMBERS for v in ok]
NUMBER_REJECTED = [(name, v) for name, _, bad in NUMBERS for v in bad]


@pytest.mark.parametrize("variable", [REG, WEA])
@pytest.mark.parametrize("value, expected", URL_ACCEPTED)
def test_accepted_urls_load(monkeypatch: pytest.MonkeyPatch, variable: str, value: str, expected: str) -> None:
    settings = load(monkeypatch, {**GOOD, variable: value})
    assert getattr(settings, variable.lower()) == expected


@pytest.mark.parametrize("variable", [REG, WEA])
@pytest.mark.parametrize("value", URL_REJECTED)
def test_rejected_urls_stop_startup(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {**GOOD, variable: value})
    assert f"{variable}: " in str(info.value)
    assert "URL" in str(info.value)  # the rule is named
    assert chain(info.value) == [info.value]


@pytest.mark.parametrize("variable", [REG, WEA])
def test_a_missing_url_stops_startup(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    env = {k: v for k, v in GOOD.items() if k != variable}
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, env)
    assert f"{variable}: required" in str(info.value)


@pytest.mark.parametrize("variable, value", NUMBER_ACCEPTED)
def test_accepted_numbers_load(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    settings = load(monkeypatch, {**GOOD, variable: value})
    assert getattr(settings, variable.lower()) == float(value)


@pytest.mark.parametrize("variable, value", NUMBER_REJECTED)
def test_rejected_numbers_stop_startup(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {**GOOD, variable: value})
    assert f"{variable}: must be" in str(info.value)  # the variable and its rule
    assert chain(info.value) == [info.value]  # no pydantic error stays in the chain


def test_defaults_equal_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(monkeypatch, GOOD)
    assert settings.registry_base_url == GOOD[REG]
    assert settings.weather_base_url == GOOD[WEA]
    assert settings.registry_timeout_seconds == 2
    assert settings.registry_retries == 1
    assert settings.weather_timeout_seconds == 12
    assert settings.weather_retries == 0
    assert settings.retry_delay_seconds == 0.3


def test_every_bad_variable_is_named_in_one_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {REG_T: "0", WEA_R: "9"})
    for name in (REG, WEA, REG_T, WEA_R):
        assert f"{name}: " in str(info.value)


# The .env file and the environment.


def test_dot_env_is_read_next_to_config_py_not_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service, elsewhere = tmp_path / "service", tmp_path / "cwd"
    service.mkdir()
    elsewhere.mkdir()
    (service / ".env").write_text(f"{REG}=http://from-service-dir:1\n{WEA}=http://from-service-dir:2\n")
    (elsewhere / ".env").write_text(f"{REG}=http://from-cwd:1\n{WEA}=http://from-cwd:2\n")
    monkeypatch.setattr(config, "SERVICE_DIR", service)
    monkeypatch.chdir(elsewhere)
    assert load_settings().registry_base_url == "http://from-service-dir:1"


def test_a_real_variable_beats_dot_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{REG}={GOOD[REG]}\n{WEA}={GOOD[WEA]}\n{REG_T}=5\n")
    monkeypatch.setenv(REG_T, "7")
    assert load_settings(str(env_file)).registry_timeout_seconds == 7


@pytest.mark.parametrize("variable", [REG_T, REG_R, DELAY])
def test_an_empty_real_variable_beats_dot_env_and_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variable: str
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{REG}={GOOD[REG]}\n{WEA}={GOOD[WEA]}\n{variable}=1\n")
    monkeypatch.setenv(variable, "")
    with pytest.raises(ConfigError) as info:
        load_settings(str(env_file))
    assert f"{variable}: " in str(info.value)


def test_an_empty_real_url_beats_dot_env_and_is_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{REG}={GOOD[REG]}\n{WEA}={GOOD[WEA]}\n")
    monkeypatch.setenv(WEA, "")
    with pytest.raises(ConfigError) as info:
        load_settings(str(env_file))
    assert f"{WEA}: " in str(info.value)


def test_other_keys_in_dot_env_are_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{REG}={GOOD[REG]}\n{WEA}={GOOD[WEA]}\nSOMETHING_ELSE=1\n")
    assert load_settings(str(env_file)).registry_base_url == GOOD[REG]


# Secrets: no value reaches a repr, a message, a traceback, or the exception chain.

LEAK = "LEAKMARK"
LEAKY = [
    (REG, f"ftp://user:{LEAK}pw@host/x"),
    (WEA, f"http://user:{LEAK}pw@example.com"),
    (REG, f"http://example.com/x?token={LEAK}url"),
    (WEA, f"http://example.com/x#{LEAK}frag"),
    (REG_T, f"3{LEAK}"),
    (REG_R, f"2{LEAK}"),
    (WEA_T, f"3{LEAK}"),
    (WEA_R, f"2{LEAK}"),
    (DELAY, f"1{LEAK}"),
]


@pytest.mark.parametrize("variable, value", LEAKY)
def test_a_rejected_value_is_never_in_the_error(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    with pytest.raises(ConfigError) as info:
        load(monkeypatch, {**GOOD, variable: value})
    assert f"{variable}: " in str(info.value)
    assert LEAK not in str(info.value)
    assert LEAK not in "".join(traceback.format_exception(info.value))
    assert all(LEAK not in str(e) for e in chain(info.value))


def test_repr_and_str_never_show_the_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load(
        monkeypatch,
        {REG: "https://registry-host.example.com/REGMARK", WEA: "https://weather-host.example.com/WEAMARK"},
    )
    assert "registry_timeout_seconds=2.0" in repr(settings)  # the repr exists and shows other fields
    for text in (repr(settings), str(settings)):
        for marker in ("registry-host", "weather-host", "REGMARK", "WEAMARK", "https://"):
            assert marker not in text


# .env.example


def test_every_setting_is_in_env_example_and_the_other_way_round() -> None:
    text = (SERVICE_DIR / ".env.example").read_text()
    in_example = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    assert in_example == {name.upper() for name in Settings.model_fields}


def test_env_example_loads_with_the_documented_defaults(tmp_path: Path) -> None:
    copy = tmp_path / ".env"
    shutil.copy(SERVICE_DIR / ".env.example", copy)
    settings = load_settings(str(copy))
    assert settings.registry_timeout_seconds == 2
    assert settings.registry_retries == 1
    assert settings.weather_timeout_seconds == 12
    assert settings.weather_retries == 0
    assert settings.retry_delay_seconds == 0.3
