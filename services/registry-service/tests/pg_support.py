"""Helpers for the PostgreSQL test fixtures."""

from collections.abc import Mapping
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import pytest

from config import same_database

SCHEMA_PREFIX = "test_"

# Set once by pytest_configure in conftest.py, before any fixture runs.
DEVELOPER_DATABASE_URL: str | None = None


def capture_developer_database_url(environ: Mapping[str, str]) -> str | None:
    value = environ.get("DATABASE_URL")
    return value if value else None


def check_not_developer_database(test_url: str, developer_url: str | None) -> None:
    if same_database(test_url, developer_url):
        pytest.fail(
            "refusing to run: TEST_DATABASE_URL points at the same database "
            "as the developer's DATABASE_URL",
            pytrace=False,
        )


def with_url_parts(
    url: str,
    *,
    password: str | None = None,
    dbname: str | None = None,
    port: int | None = None,
) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    userinfo, _, hostport = netloc.rpartition("@")
    if password is not None:
        user = userinfo.partition(":")[0]
        userinfo = f"{user}:{quote(password, safe='')}"
    if port is not None:
        host = hostport.rpartition(":")[0] if hostport.count(":") == 1 else hostport
        hostport = f"{host}:{port}"
    netloc = f"{userinfo}@{hostport}" if userinfo else hostport
    path = f"/{dbname}" if dbname is not None else parts.path
    return urlunsplit((parts.scheme, netloc, path, parts.query, parts.fragment))


def with_options(url: str, options: str) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("options", options))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, quote_via=quote), parts.fragment)
    )


def check_comparable_test_url(test_url: str) -> None:
    """Refuse a TEST_DATABASE_URL the same-database comparison cannot judge."""
    try:
        parts = urlsplit(test_url.strip())
        ok = parts.scheme.lower() in ("postgres", "postgresql") and bool(parts.hostname)
        if ok:
            keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
            hostpart = parts.netloc.rpartition("@")[2]
            # The comparison cannot read these.
            ok = not (keys & {"service", "hostaddr"}) and "," not in hostpart
    except ValueError:
        ok = False
    if not ok:
        pytest.fail(
            "refusing to run: TEST_DATABASE_URL must be a postgresql:// or postgres:// "
            "URL with a host",
            pytrace=False,
        )
