"""Settings, read with pydantic-settings from the environment and the .env file next to this module.

A bad or missing variable stops startup with a ConfigError that names the variable and the rule it broke.
No message, traceback or repr ever holds a value: a URL can carry credentials.
"""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_DIR = Path(__file__).resolve().parent

URL_RULE = "must be an http:// or https:// URL with a host, and no user info, query or fragment"

# The rule each variable must follow. Messages are built from these texts, never from a value.
RULES = {
    "REGISTRY_BASE_URL": URL_RULE,
    "WEATHER_BASE_URL": URL_RULE,
    "REGISTRY_TIMEOUT_SECONDS": "must be a number greater than 0 and at most 30",
    "REGISTRY_RETRIES": "must be a whole number from 0 to 5",
    "WEATHER_TIMEOUT_SECONDS": "must be a number greater than 0 and at most 240",
    "WEATHER_RETRIES": "must be a whole number from 0 to 5",
    "RETRY_DELAY_SECONDS": "must be a number from 0 to 10",
}


class ConfigError(Exception):
    """Invalid settings. The message names variables and rules only, never a value."""


def _message(problems: list[tuple[str, str]]) -> str:
    return "Invalid settings: " + "; ".join(f"{name}: {rule}" for name, rule in problems)


def _clean_url(value: str) -> str:
    value = value.strip()
    parts = None
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number
    except ValueError:
        parts = None  # urlsplit's message can hold the netloc, so it is dropped; the error is raised below.
    if (
        parts is None
        or parts.scheme.lower() not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or "?" in value
        or "#" in value
    ):
        raise ValueError("invalid URL")  # The text is not used: messages come from RULES.
    return value.removesuffix("/")


class Settings(BaseSettings):
    # Environment names are the field names in upper case (the default, case-insensitive match).
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    # repr=False: a URL can carry credentials, so repr and str of the settings never show it.
    registry_base_url: str = Field(repr=False)
    weather_base_url: str = Field(repr=False)
    registry_timeout_seconds: float = Field(2.0, gt=0, le=30, allow_inf_nan=False)
    registry_retries: int = Field(1, ge=0, le=5)
    weather_timeout_seconds: float = Field(12.0, gt=0, le=240, allow_inf_nan=False)
    weather_retries: int = Field(0, ge=0, le=5)
    retry_delay_seconds: float = Field(0.3, ge=0, le=10, allow_inf_nan=False)

    @field_validator("registry_base_url", "weather_base_url")
    @classmethod
    def base_url_is_clean(cls, value: str) -> str:
        return _clean_url(value)


def load_settings(env_file: str | None = None) -> Settings:
    """Build Settings from the environment and .env (next to this module, not the working directory)."""
    path = env_file if env_file is not None else str(SERVICE_DIR / ".env")
    problems: list[tuple[str, str]] = []
    try:
        return Settings(_env_file=path)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            name = str(error["loc"][0]).upper() if error["loc"] else "settings"
            rule = "required" if error["type"] == "missing" else RULES.get(name, "is invalid")
            if (name, rule) not in problems:
                problems.append((name, rule))
    # Raised after the handler, so the pydantic error (which holds the values) is not in __context__.
    raise ConfigError(_message(problems)) from None
