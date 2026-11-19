"""Settings, read with pydantic-settings from the environment and the .env file next to this module.

A bad or missing variable stops startup with a ConfigError that names the variable and the rule it broke.
No message, traceback or repr ever holds a value: values can be the API key or a URL that carries one.
"""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_DIR = Path(__file__).resolve().parent

# A host that is exactly one of these may use http with an API key (for local fakes).
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# The rule each variable must follow. Messages are built from these texts, never from a value.
RULES = {
    "PROVIDER_BASE_URL": "must be an http:// or https:// URL with a host",
    "PROVIDER_API_KEY": "must be text",
    "PROVIDER_TIMEOUT_SECONDS": "must be a number greater than 0 and at most 30",
    "PROVIDER_RETRIES": "must be a whole number from 0 to 5",
    "PROVIDER_RETRY_DELAY_SECONDS": "must be a number from 0 to 10",
    "FRESH_FOR_SECONDS": "must be a number greater than 0",
    "STALE_MAX_AGE_SECONDS": "must be a number not smaller than FRESH_FOR_SECONDS",
    "COOLDOWN_SECONDS": "must be a number of 0 or more",
    "CACHE_MAX_CELLS": "must be a whole number of 1 or more",
}
HTTPS_RULE = "must be https:// when PROVIDER_API_KEY is set (the key is in the query string); local hosts are excepted"


class ConfigError(Exception):
    """Invalid settings. The message names variables and rules only, never a value."""


def _message(problems: list[tuple[str, str]]) -> str:
    return "Invalid settings: " + "; ".join(f"{name}: {rule}" for name, rule in problems)


def _https_or_local(url: str) -> bool:
    parts = urlsplit(url)  # The URL was already checked, so this cannot fail.
    return parts.scheme.lower() == "https" or (parts.hostname or "").lower() in LOCAL_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    # repr=False: the URL can carry a token, so repr and str of the settings never show it.
    PROVIDER_BASE_URL: str = Field(repr=False)
    PROVIDER_API_KEY: SecretStr = SecretStr("")
    PROVIDER_TIMEOUT_SECONDS: float = Field(3.0, gt=0, le=30, allow_inf_nan=False)
    PROVIDER_RETRIES: int = Field(2, ge=0, le=5)
    PROVIDER_RETRY_DELAY_SECONDS: float = Field(0.5, ge=0, le=10, allow_inf_nan=False)
    FRESH_FOR_SECONDS: float = Field(10800, gt=0, allow_inf_nan=False)
    STALE_MAX_AGE_SECONDS: float = Field(86400, allow_inf_nan=False)
    COOLDOWN_SECONDS: float = Field(30, ge=0, allow_inf_nan=False)
    CACHE_MAX_CELLS: int = Field(2000, ge=1)

    @field_validator("PROVIDER_API_KEY", mode="before")
    @classmethod
    def key_is_stripped(cls, value: object) -> object:
        # Surrounding spaces are removed, and a key of only spaces counts as empty.
        return value.strip() if isinstance(value, str) else value

    @field_validator("PROVIDER_BASE_URL")
    @classmethod
    def base_url_is_http_with_a_host(cls, value: str) -> str:
        value = value.strip()
        parts = None
        try:
            parts = urlsplit(value)
        except ValueError:
            pass  # urlsplit's message can hold the netloc, so it is dropped; the error is raised below.
        if parts is None or parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError("invalid URL")  # The text is not used: messages come from RULES.
        return value

    @model_validator(mode="after")
    def cross_field_rules(self) -> "Settings":
        problems: list[tuple[str, str]] = []
        if self.api_key() and not _https_or_local(self.PROVIDER_BASE_URL):
            problems.append(("PROVIDER_BASE_URL", HTTPS_RULE))
        if self.STALE_MAX_AGE_SECONDS < self.FRESH_FOR_SECONDS:
            problems.append(("STALE_MAX_AGE_SECONDS", RULES["STALE_MAX_AGE_SECONDS"]))
        if problems:
            # Not a ValueError, so pydantic lets it through unchanged.
            raise ConfigError(_message(problems))
        return self

    def api_key(self) -> str:
        return self.PROVIDER_API_KEY.get_secret_value()


def load_settings(env_file: Path | None = None) -> Settings:
    """Build Settings from the environment and .env (next to this module, not the working directory)."""
    path = env_file if env_file is not None else SERVICE_DIR / ".env"
    problems: list[tuple[str, str]] = []
    try:
        return Settings(_env_file=path)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            name = str(error["loc"][0]) if error["loc"] else "settings"
            rule = "required" if error["type"] == "missing" else RULES.get(name, "is invalid")
            if (name, rule) not in problems:
                problems.append((name, rule))
    # Raised after the handler, so the pydantic error (which holds the values) is not in __context__.
    raise ConfigError(_message(problems)) from None
