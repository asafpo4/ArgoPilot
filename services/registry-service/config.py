"""Configuration: the DATABASE_URL target and .env loading."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

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


def load_environment(env_file: Path | None = None) -> None:
    """Fill missing environment variables from a .env file; never override."""
    load_dotenv(env_file if env_file is not None else SERVICE_DIR / ".env", override=False)


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
    return all(s.isascii() and (s.isdigit() or (multi and s == "")) for s in segments)


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
            consistent = _libpq_agrees_with_urlsplit(normalized)
        except Exception:
            consistent = False
        if not consistent:
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
        if port.isascii() and port.isdigit():
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


load_environment()
