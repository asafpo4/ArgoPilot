"""Configuration: the DATABASE_URL target and .env loading."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
        """Built from libpq's parse only: never the query string, never the URL text."""
        try:
            params = conninfo_to_dict(self.url)
            if not _libpq_agrees_with_urlsplit(self.url):
                return "postgresql://***"  # urlsplit and libpq disagree: show nothing
        except Exception:
            return "postgresql://***"
        user = params.get("user")
        host = params.get("host") or ""
        if ":" in host and "," not in host and not host.startswith("/"):
            host = f"[{host}]"
        netloc = quote(host, safe=",:[]")
        if params.get("port"):
            netloc += ":" + quote(params["port"], safe=",")
        if user is not None:
            userinfo = quote(user, safe="") + (":***" if params.get("password") else "")
            netloc = f"{userinfo}@{netloc}"
        elif params.get("password"):
            netloc = f":***@{netloc}"
        dbname = params.get("dbname")
        if dbname and ("@" in dbname or "/" in dbname):
            return "postgresql://***"  # libpq read part of a misplaced password as the name
        path = "/" + quote(dbname, safe="") if dbname else ""
        return f"postgresql://{netloc}{path}"

    def __repr__(self) -> str:
        return f"PostgresTarget(url={self._redacted()!r})"

    def __str__(self) -> str:
        return self._redacted()


def postgres_connect_args(url: str) -> dict[str, str | int]:
    """libpq parameters for psycopg, with the connect and lock timeouts (entry 24).

    lock_timeout is appended to any options already in the URL, never replacing them.
    """
    params: dict[str, str | int] = dict(conninfo_to_dict(url))
    options = params.get("options")
    lock_option = "-c lock_timeout=5000"
    params["options"] = f"{options} {lock_option}" if options else lock_option
    params["connect_timeout"] = 5
    return params


class Settings(BaseSettings):
    """Settings read from the environment, then from .env. A real variable wins over .env."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    # repr=False: the URL can hold a password, and repr and str must never show it.
    DATABASE_URL: str | None = Field(default=None, repr=False)

    # The S3 bucket for plot photos and its region. Never credentials: boto3 finds those itself.
    AWS_S3_BUCKET: str | None = None
    AWS_REGION: str | None = None

    @field_validator("DATABASE_URL")
    @classmethod
    def database_url_is_valid(cls, value: str | None) -> str | None:
        # ConfigError is not a ValueError, so pydantic lets it through unchanged.
        parse_database_url(value)
        return value

    @property
    def target(self) -> SqliteTarget | PostgresTarget:
        return parse_database_url(self.DATABASE_URL)


def load_settings(env_file: Path | None = None) -> Settings:
    """Build Settings. Errors never show the input value."""
    path = env_file if env_file is not None else SERVICE_DIR / ".env"
    try:
        return Settings(_env_file=path)
    except ValidationError:
        pass  # Raised below, outside this handler, so the error keeps no __context__.
    raise ConfigError("Invalid settings") from None


def valid_port(value: str) -> bool:
    """Plain ASCII digits within 1..65535 (leading zeros allowed)."""
    return value.isascii() and value.isdigit() and 1 <= int(value) <= 65535


def _norm_port(value: str) -> str:
    return str(int(value)) if value.isascii() and value.isdigit() else value


def _netloc_hosts_and_ports(netloc: str) -> tuple[list[str], list[str]]:
    """Split the host part of a netloc into per-host names and ports (as written)."""
    hostport = netloc.rpartition("@")[2]
    hosts, ports = [], []
    for segment in hostport.split(","):
        if segment.startswith("["):
            host, _, rest = segment[1:].partition("]")
            port = rest[1:] if rest.startswith(":") else ""
        else:
            host, _, port = segment.rpartition(":") if ":" in segment else (segment, "", "")
        hosts.append(unquote(host).lower())
        ports.append(port)
    return hosts, ports


def _libpq_agrees_with_urlsplit(url: str) -> bool:
    """libpq decides what a URL means; reject URLs where urlsplit reads it differently.

    For user, password, host, port and database name: a non-empty urlsplit value must equal
    libpq's value. Where urlsplit finds nothing, libpq may supply it (socket form, defaults).
    An unencoded @ in the path is always rejected: it means a password was cut at a /.
    """
    params = conninfo_to_dict(url)
    host = params.get("host") or ""
    port = params.get("port")
    if "@" in host:
        return False
    if port is not None and not _port_ok(port, host):
        return False
    parts = urlsplit(url)
    if "@" in parts.path or "@" in parts.query or "@" in parts.fragment:
        return False
    for key, raw in (("user", parts.username), ("password", parts.password)):
        if raw and params.get(key) != unquote(raw):
            return False
    path = parts.path[1:] if parts.path.startswith("/") else parts.path
    if path and params.get("dbname") != unquote(path):
        return False
    hosts, ports = _netloc_hosts_and_ports(parts.netloc)
    if any(hosts):
        if [h.lower() for h in host.split(",")] != hosts:
            return False
    if any(ports):
        got_ports = (port or "").split(",")
        if len(got_ports) != len(ports):
            return False
        for want, got in zip(ports, got_ports):
            if want and (not got or _norm_port(want) != _norm_port(got)):
                return False
    return True


def _port_ok(port: str, host: str) -> bool:
    segments = port.split(",")
    if len(segments) != len(host.split(",")):
        return False
    multi = len(segments) > 1
    return all(valid_port(s) or (multi and s == "") for s in segments)


def parse_database_url(
    value: str | None, base_dir: Path = SERVICE_DIR
) -> SqliteTarget | PostgresTarget:
    if value is None or not value.strip():
        return SqliteTarget(DEFAULT_SQLITE_PATH)
    value = value.strip()
    parts = None
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
    except ValueError:
        pass  # urlsplit's message can hold the netloc, so it is dropped. Raised below, outside this handler.
    if parts is None:
        raise ConfigError("DATABASE_URL is not a valid URL") from None
    if scheme in ("postgres", "postgresql"):
        rest = value[len(parts.scheme):]
        normalized = "postgresql" + rest
        try:
            consistent = _libpq_agrees_with_urlsplit(normalized)
        except Exception:
            consistent = False
        if not consistent:
            # Fixed message: libpq's error text can hold the password. Raised here, outside the handler
            # above, so the error has no __context__; `from None` also marks the context as suppressed.
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


def _identity(url: str | None) -> tuple[frozenset[tuple[str, str]], str | None] | None:
    """({(host, port), ...}, database name); the name is None when unknown.

    A host list (netloc or ?host=) gives several pairs.
    """
    if url is None:
        return None
    try:
        url = url.strip()
        scheme = urlsplit(url).scheme
        if scheme.lower() not in ("postgres", "postgresql"):
            return None
        params = conninfo_to_dict("postgresql" + url[len(scheme):])
    except Exception:
        return None
    hosts = (params.get("host") or "").lower().split(",")
    ports = (params.get("port") or "").split(",")
    pairs = set()
    for i, host in enumerate(hosts):
        port = ports[i] if len(ports) == len(hosts) else ports[0]
        port = port or "5432"
        if not valid_port(port):
            return None  # libpq may read it differently from plain digits
        port = str(int(port))
        if host in _LOCAL_HOSTS:
            host = "localhost"
        pairs.add((host, port))
    return frozenset(pairs), params.get("dbname") or params.get("user") or None


def same_database(url_a: str | None, url_b: str | None) -> bool:
    a, b = _identity(url_a), _identity(url_b)
    if a is None or b is None:
        return False
    # An unknown database name may be any name, so it matches any name (a wrong "same"
    # only makes the tests refuse to run; a wrong "different" could hit the real database).
    return bool(a[0] & b[0]) and (a[1] is None or b[1] is None or a[1] == b[1])
