"""The Open-Meteo provider: the only code that knows Open-Meteo's field names (spec 4.1 and 4.2).

One call is one attempt. It returns a validated ProviderForecast, or a Failure with a fixed kind. It never
logs, and no URL, request, body or exception message ever goes into a kind, so no secret can reach a log or
a failure. Retries, the cool-down and the cache belong to the forecast service.
"""

import asyncio
import datetime as dt
import json
import logging
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from clock import Clock

# The body is read as a stream and cut off here. A hostile or broken provider cannot make us read more.
MAX_BODY_BYTES = 1024 * 1024
ROWS = 7
MAX_OFFSET_SECONDS = 18 * 3600

# Open-Meteo's names. They appear in this module only (and in the fakes that imitate it).
ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"

_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")

# httpx logs every request URL at INFO, and our URL can carry the API key.
HTTP_LOGGERS = ("httpx", "httpcore")


@dataclass(frozen=True)
class Day:
    date: dt.date
    et0_mm: float
    rain_mm: float


@dataclass(frozen=True)
class ProviderForecast:
    rows: tuple[Day, ...]
    tz: dt.tzinfo  # The time zone of the point: "today" is the date there.


@dataclass(frozen=True)
class Failure:
    """Why an attempt failed. `kind` is one of a fixed set of words, never text from the provider."""

    kind: str


class Provider(Protocol):
    async def fetch(self, lat: Decimal, lon: Decimal) -> ProviderForecast | Failure:
        """One attempt for the node (lat, lon), each with one decimal."""
        ...


def silence_http_logs() -> None:
    """Keep httpx and httpcore at WARNING, so a request URL (and the key in it) is never logged."""
    for name in HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _zone(payload: dict) -> dt.tzinfo | None:
    """The provider's IANA zone, else its fixed offset (a whole number within +-18 hours), else None."""
    name = payload.get("timezone")
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass  # An unknown name, a path, or a directory: try the fixed offset instead.
    offset = payload.get("utc_offset_seconds")
    if isinstance(offset, int) and not isinstance(offset, bool) and abs(offset) <= MAX_OFFSET_SECONDS:
        return dt.timezone(dt.timedelta(seconds=offset))
    return None


def _dates(items: list) -> list[dt.date] | None:
    dates: list[dt.date] = []
    for item in items:
        match = _DATE.fullmatch(item) if isinstance(item, str) else None
        if match is None:
            return None
        try:
            dates.append(dt.date(int(match[1]), int(match[2]), int(match[3])))
        except ValueError:
            return None
    return dates


def _number(value: object) -> tuple[float | None, str | None]:
    """The value as a float, or the rule it breaks. A real, finite, non-negative number only."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "bad_value"  # null, a string, a boolean, a list, an object
    try:
        number = float(value)
    except OverflowError:
        return None, "not_finite"  # a whole number too large for a float
    if not math.isfinite(number):
        return None, "not_finite"
    if number < 0:
        return None, "negative"
    return number, None


def validate(payload: object, now: dt.datetime) -> ProviderForecast | Failure:
    """Accept the provider's answer whole, or not at all (spec 4.2). `now` is our time when it arrived."""
    if not isinstance(payload, dict):
        return Failure("invalid not_an_object")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        return Failure("invalid missing_daily")
    series = {name: daily.get(name) for name in ("time", ET0, RAIN)}
    if not all(isinstance(items, list) for items in series.values()):
        return Failure("invalid missing_field")
    if any(len(items) != ROWS for items in series.values()):  # type: ignore[arg-type]
        return Failure("invalid wrong_length")
    units = payload.get("daily_units")
    if not isinstance(units, dict) or units.get(ET0) != "mm" or units.get(RAIN) != "mm":
        return Failure("invalid units")
    tz = _zone(payload)
    if tz is None:
        return Failure("invalid unknown_zone")
    dates = _dates(series["time"])  # type: ignore[arg-type]
    if dates is None:
        return Failure("invalid bad_date")
    if any(later - earlier != dt.timedelta(days=1) for earlier, later in zip(dates, dates[1:])):
        return Failure("invalid date_gap")
    if dates[0] != now.astimezone(tz).date():
        return Failure("invalid first_row_not_today")
    numbers: dict[str, list[float]] = {ET0: [], RAIN: []}
    for name in (ET0, RAIN):
        for value in series[name]:  # type: ignore[union-attr]
            number, rule = _number(value)
            if number is None:
                return Failure(f"invalid {rule}")
            numbers[name].append(number)
    rows = tuple(Day(date, et0, rain) for date, et0, rain in zip(dates, numbers[ET0], numbers[RAIN]))
    return ProviderForecast(rows=rows, tz=tz)


async def _read_limited(response: httpx.Response) -> bytes | None:
    """The decoded body, read in chunks, or None as soon as it grows past the cap (the rest is not read)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


class OpenMeteoProvider:
    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, api_key: str, timeout: float, clock: Clock
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._clock = clock
        silence_http_logs()

    def _params(self, lat: Decimal, lon: Decimal) -> dict[str, str]:
        params = {
            "latitude": format(lat, "f"),
            "longitude": format(lon, "f"),
            "daily": f"{ET0},{RAIN}",
            "forecast_days": str(ROWS),
            "timezone": "auto",
        }
        if self._api_key:
            params["apikey"] = self._api_key
        return params

    async def _attempt(self, params: dict[str, str]) -> ProviderForecast | Failure:
        # timeout=None: httpx's own per-phase timeouts are off. The one total deadline is in `fetch`.
        async with self._client.stream(
            "GET", self._base_url, params=params, follow_redirects=False, timeout=None
        ) as response:
            if response.status_code != 200:
                return Failure(f"status {response.status_code}")
            raw = await _read_limited(response)
        if raw is None:
            return Failure("invalid too_large")
        now = self._clock.now()  # when the answer arrived, for "the first row is today"
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError):  # not JSON, bad UTF-8, an integer too long, or nested too deep
            return Failure("not_json")
        return validate(payload, now)

    async def fetch(self, lat: Decimal, lon: Decimal) -> ProviderForecast | Failure:
        """One attempt, inside one total deadline that covers waiting for a connection, connecting and reading."""
        result: ProviderForecast | Failure | None = None
        failure: Failure | None = None
        try:
            async with asyncio.timeout(self._timeout):
                result = await self._attempt(self._params(lat, lon))
        except (TimeoutError, httpx.TimeoutException):
            failure = Failure("timeout")
        except httpx.HTTPError:
            failure = Failure("transport")
        # Returned after the handlers, and built from fixed words: no exception text, URL or key is kept.
        if failure is not None:
            return failure
        assert result is not None
        return result
