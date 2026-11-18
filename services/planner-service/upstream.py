"""The upstream client (spec 4.1 to 4.3) and the checks of the upstream answers (spec 4.4).

The client has no clock and no sleep of its own: the sleep is injected. A failure carries a
service name, a kind and a Retry-After, and nothing that came from the wire: no URL, no plot id,
no body, no exception message (spec 4.5). The checks work on the decoded JSON.
A failed check raises InvalidAnswer with a rule name only.
"""

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from engine import WeatherRow

logger = logging.getLogger(__name__)

SOURCE = "open-meteo"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UTC_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")


_DEFAULT_RETRY_AFTER = 5


class UpstreamFailure(Exception):
    """A call that ended in failure after its retries. Holds names and numbers only."""

    def __init__(self, service: str, kind: str, retry_after: int) -> None:
        super().__init__(f"{service} {kind}")
        self.service = service
        self.kind = kind
        self.retry_after = retry_after


class NotFound(Exception):
    """The upstream answered 404 and the caller asked to see that as an answer."""


def _retry_after(value: str | None) -> int:
    # A whole number from 1 to 60 is kept; anything else (absent, 0, 61, text, a date) gives 5.
    if value is not None:
        text = value.strip()
        if text.isascii() and text.isdigit() and 1 <= int(text) <= 60:
            return int(text)
    return _DEFAULT_RETRY_AFTER


def forecast_query(lat: float, lon: float, days: int) -> dict[str, str]:
    """The query of the forecast call. repr gives the shortest decimal text that reads back the same."""
    return {"lat": repr(lat), "lon": repr(lon), "days": str(days)}


class Upstream:
    """One upstream service: a shared client, a hard deadline per attempt, and retries.

    retry_4xx=False is the registry style: a timeout, a transport error and a 5xx are retried,
    and every other failure is final. retry_4xx=True is the weather style: every failure is retried.
    """

    def __init__(
        self,
        service: str,
        base_url: str,
        http: httpx.AsyncClient,
        timeout: float,
        retries: int,
        delay: float,
        sleep: Callable[[float], Awaitable[None]],
        retry_4xx: bool,
    ) -> None:
        self._service = service
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._timeout = timeout
        self._retries = retries
        self._delay = delay
        self._sleep = sleep
        self._retry_everything = retry_4xx

    async def get_json(
        self, path: str, params: dict[str, str] | None = None, *, not_found_ok: bool = False
    ) -> object:
        url = self._base_url + path
        kind = ""
        retry_after = _DEFAULT_RETRY_AFTER
        for attempt in range(1, self._retries + 2):
            if attempt > 1:
                await self._sleep(self._delay)
            kind, retry_after, retryable, body = await self._attempt(url, params, attempt, not_found_ok)
            if not kind:
                return body
            if not retryable:
                break
        # Raised here, outside every except block: no httpx exception is left in __context__.
        raise UpstreamFailure(self._service, kind, retry_after)

    async def _attempt(
        self, url: str, params: dict[str, str] | None, attempt: int, not_found_ok: bool
    ) -> tuple[str, int, bool, object]:
        """One attempt. Returns (kind, retry_after, retryable, body); an empty kind is a success."""
        response: httpx.Response | None = None
        kind = ""
        try:
            # The deadline covers the whole call: waiting for a connection, connecting, the body.
            async with asyncio.timeout(self._timeout):
                response = await self._http.get(url, params=params, follow_redirects=False)
        except (TimeoutError, httpx.TimeoutException):
            kind = "timeout"
        except httpx.HTTPError:
            kind = "transport"
        except Exception as exc:
            # Logged by class only: the message of an unknown exception can hold anything.
            logger.warning("%s attempt %d unexpected: %s", self._service, attempt, type(exc).__name__)
            return "transport", _DEFAULT_RETRY_AFTER, True, None
        # The except block has ended: nothing below carries an httpx exception in its context.
        if response is None:
            return self._failed(kind, attempt, _DEFAULT_RETRY_AFTER, True)
        if response.status_code == 404 and not_found_ok:
            raise NotFound()
        if response.status_code != 200:
            code = response.status_code
            return self._failed(
                f"status {code}",
                attempt,
                _retry_after(response.headers.get("Retry-After")),
                self._retry_everything or code >= 500,
            )
        body: object = None
        try:
            body = response.json()
        except ValueError:
            kind = "not_json"
        if kind:
            return self._failed(kind, attempt, _DEFAULT_RETRY_AFTER, self._retry_everything)
        return "", _DEFAULT_RETRY_AFTER, False, body

    def _failed(self, kind: str, attempt: int, retry_after: int, retryable: bool) -> tuple[str, int, bool, object]:
        logger.warning("%s attempt %d %s", self._service, attempt, kind)
        return kind, retry_after, retryable, None


class InvalidAnswer(Exception):
    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


@dataclass(frozen=True)
class PlotData:
    crop_id: str
    soil_id: str
    emitter_id: str
    planting_date: date
    area_m2: float
    row_spacing_m: float
    emitter_spacing_m: float
    lat: float
    lon: float


@dataclass(frozen=True)
class Forecast:
    stale: bool
    fetched_at: str
    rows: tuple[WeatherRow, ...]


def _object(body: object, rule: str) -> dict:
    if not isinstance(body, dict):
        raise InvalidAnswer(rule)
    return body


def _field(body: dict, key: str) -> object:
    if key not in body:
        raise InvalidAnswer(f"{key} missing")
    return body[key]


def _number(value: object, name: str) -> float:
    # A boolean is an int in Python, but it is not a number here.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidAnswer(f"{name} not a number")
    if not math.isfinite(value):
        raise InvalidAnswer(f"{name} not finite")
    return value


def _positive(value: object, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise InvalidAnswer(f"{name} not positive")
    return number


def _non_negative(value: object, name: str) -> float:
    number = _number(value, name)
    if number < 0:
        raise InvalidAnswer(f"{name} negative")
    return number


def _within(value: object, name: str, limit: float) -> float:
    number = _number(value, name)
    if not -limit <= number <= limit:
        raise InvalidAnswer(f"{name} out of range")
    return number


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidAnswer(f"{name} not text")
    return value


def _date(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise InvalidAnswer(f"{name} not a date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidAnswer(f"{name} not a date") from None


def parse_plot(body: object) -> PlotData:
    obj = _object(body, "plot not an object")
    return PlotData(
        crop_id=_text(_field(obj, "crop_id"), "crop_id"),
        soil_id=_text(_field(obj, "soil_id"), "soil_id"),
        emitter_id=_text(_field(obj, "emitter_id"), "emitter_id"),
        planting_date=_date(_field(obj, "planting_date"), "planting_date"),
        area_m2=_positive(_field(obj, "area_m2"), "area_m2"),
        row_spacing_m=_positive(_field(obj, "row_spacing_m"), "row_spacing_m"),
        emitter_spacing_m=_positive(_field(obj, "emitter_spacing_m"), "emitter_spacing_m"),
        lat=_within(_field(obj, "lat"), "lat", 90),
        lon=_within(_field(obj, "lon"), "lon", 180),
    )


def parse_soil(body: object) -> float:
    obj = _object(body, "soil not an object")
    return _positive(_field(obj, "available_water_mm_per_m"), "available_water_mm_per_m")


def parse_emitter(body: object) -> float:
    obj = _object(body, "emitter not an object")
    return _positive(_field(obj, "flow_lph"), "flow_lph")


def _utc_time(value: object) -> str:
    if not isinstance(value, str) or not _UTC_TIME.fullmatch(value):
        raise InvalidAnswer("fetched_at not a UTC time")
    try:
        datetime.fromisoformat(value[:-1])
    except ValueError:
        raise InvalidAnswer("fetched_at not a UTC time") from None
    return value


def parse_forecast(body: object, days_requested: int) -> Forecast:
    obj = _object(body, "forecast not an object")
    stale = _field(obj, "stale")
    if not isinstance(stale, bool):
        raise InvalidAnswer("stale not a boolean")
    if _field(obj, "source") != SOURCE:
        raise InvalidAnswer("source not accepted")
    fetched_at = _utc_time(_field(obj, "fetched_at"))
    days = _field(obj, "days")
    if not isinstance(days, list):
        raise InvalidAnswer("days not a list")
    if not 1 <= len(days) <= days_requested:
        raise InvalidAnswer("days count not accepted")
    rows: list[WeatherRow] = []
    for item in days:
        entry = _object(item, "day not an object")
        day = _date(_field(entry, "date"), "date")
        if rows and day != rows[-1].date + timedelta(days=1):
            raise InvalidAnswer("dates not consecutive")
        rows.append(
            WeatherRow(
                date=day,
                et0_mm=_non_negative(_field(entry, "et0_mm"), "et0_mm"),
                rain_mm=_non_negative(_field(entry, "rain_mm"), "rain_mm"),
            )
        )
    return Forecast(stale=stale, fetched_at=fetched_at, rows=tuple(rows))
