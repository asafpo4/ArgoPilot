"""Configuration: the DATABASE_URL target and .env loading."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

SERVICE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = SERVICE_DIR / "registry.db"

_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ConfigError(Exception):
    """Invalid configuration. Messages never contain the URL or a password."""


@dataclass(frozen=True)
class SqliteTarget:
    path: Path


@dataclass(frozen=True)
class PostgresTarget:
    url: str

    def _redacted(self) -> str:
        parts = urlsplit(self.url)
        netloc = parts.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            if ":" in userinfo:
                userinfo = userinfo.split(":", 1)[0] + ":***"
            netloc = userinfo + "@" + host
        query = urlencode(
            [
                (k, "***" if k.lower() == "password" else v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
            ],
            safe="*",
        )
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))

    def __repr__(self) -> str:
        return f"PostgresTarget(url={self._redacted()!r})"

    def __str__(self) -> str:
        return self._redacted()


def load_environment(env_file: Path | None = None) -> None:
    """Fill missing environment variables from a .env file; never override."""
    load_dotenv(env_file if env_file is not None else SERVICE_DIR / ".env", override=False)


def parse_database_url(
    value: str | None, base_dir: Path = SERVICE_DIR
) -> SqliteTarget | PostgresTarget:
    if value is None or not value.strip():
        return SqliteTarget(DEFAULT_SQLITE_PATH)
    value = value.strip()
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
    except ValueError:
        raise ConfigError("DATABASE_URL is not a valid URL") from None
    if scheme in ("postgres", "postgresql"):
        rest = value[len(parts.scheme):]
        normalized = "postgresql" + rest
        try:
            conninfo_to_dict(normalized)
        except Exception:
            # Fixed message, original suppressed: libpq's error text can hold the password.
            raise ConfigError("DATABASE_URL is not a valid PostgreSQL URL") from None
        return PostgresTarget(normalized)
    if scheme == "sqlite":
        if parts.netloc:
            raise ConfigError("DATABASE_URL with scheme 'sqlite' must look like sqlite:///path")
        path = parts.path[1:] if parts.path.startswith("/") else parts.path
        if not path:
            raise ConfigError("DATABASE_URL with scheme 'sqlite' has no file path")
        p = Path(path)
        return SqliteTarget(p if p.is_absolute() else base_dir / p)
    if _SCHEME_RE.fullmatch(parts.scheme or ""):
        raise ConfigError(
            f"DATABASE_URL has unsupported scheme {scheme!r}; "
            "use postgresql://, postgres:// or sqlite:///"
        )
    raise ConfigError(
        "DATABASE_URL is not a valid URL; use postgresql://, postgres:// or sqlite:///"
    )


def _identity(url: str | None) -> tuple[str, int, str] | None:
    if url is None:
        return None
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ("postgres", "postgresql"):
            return None
        host = (parts.hostname or "").lower()
        port = parts.port or 5432
    except ValueError:
        return None
    if host in _LOCAL_HOSTS:
        host = "localhost"
    return host, port, parts.path.lstrip("/")


def same_database(url_a: str | None, url_b: str | None) -> bool:
    a, b = _identity(url_a), _identity(url_b)
    return a is not None and a == b


load_environment()
