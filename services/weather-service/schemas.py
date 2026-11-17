"""The forecast request text rules (spec 2.1) and the response models (spec 2.2)."""

import datetime as dt
import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from errors import RequestError

MAX_TEXT_LENGTH = 32

# ASCII digits only: [0-9] never matches another script's digits. `fullmatch` is used because `$` would
# let a trailing newline through. The exponent has at most three digits, because Python's Decimal raises
# InvalidOperation for a huge exponent, which would be a 500 instead of a 422.
_COORDINATE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?")
_DAYS = re.compile(r"[1-7]")

LAT_LIMIT = Decimal(90)
LON_LIMIT = Decimal(180)

# Fixed texts: a message names the field and the rule, and never echoes what the caller sent.
MESSAGES = {
    "lat": "must be a number from -90 to 90, as plain ASCII text such as 31.25 or 1e-05",
    "lon": "must be a number from -180 to 180, as plain ASCII text such as 34.79 or 1e-05",
    "days": "must be one digit from 1 to 7",
}


class ForecastQuery(NamedTuple):
    lat: Decimal
    lon: Decimal
    days: int


def _to_decimal(text: str) -> Decimal:
    return Decimal(text)


def _coordinate(text: str, limit: Decimal) -> Decimal | None:
    """The exact value of a coordinate text, or None if the text or the value is not accepted."""
    if len(text) > MAX_TEXT_LENGTH or not _COORDINATE.fullmatch(text):
        return None
    try:
        value = _to_decimal(text)
    except InvalidOperation:
        return None  # A second line of defence: the pattern already limits the exponent.
    # The range is checked on the exact decimal value, never through a float.
    return value if -limit <= value <= limit else None


def parse_forecast_query(items: Sequence[tuple[str, str]]) -> ForecastQuery:
    """Check the raw query items (every pair, so a repeated parameter is seen) against spec 2.1.

    Raises RequestError with every problem found, in the order lat, lon, days. Other parameters are ignored.
    """
    problems: list[tuple[str, str]] = []
    values: dict[str, str] = {}
    for name in ("lat", "lon", "days"):
        found = [value for key, value in items if key == name]
        if not found:
            problems.append((name, "is required"))
        elif len(found) > 1:
            problems.append((name, "must appear exactly once"))
        else:
            values[name] = found[0]

    lat = lon = None
    days = 0
    if "lat" in values:
        lat = _coordinate(values["lat"], LAT_LIMIT)
        if lat is None:
            problems.append(("lat", MESSAGES["lat"]))
    if "lon" in values:
        lon = _coordinate(values["lon"], LON_LIMIT)
        if lon is None:
            problems.append(("lon", MESSAGES["lon"]))
    if "days" in values:
        if _DAYS.fullmatch(values["days"]):
            days = int(values["days"])
        else:
            problems.append(("days", MESSAGES["days"]))

    if problems or lat is None or lon is None:
        raise RequestError(sorted(problems, key=lambda p: ("lat", "lon", "days").index(p[0])))
    return ForecastQuery(lat, lon, days)


class DayOut(BaseModel):
    """One row of the answer. No field has a default: a missing number must never become a zero."""

    model_config = ConfigDict(extra="forbid")

    date: dt.date
    et0_mm: float = Field(allow_inf_nan=False)
    rain_mm: float = Field(allow_inf_nan=False)


class ForecastOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(allow_inf_nan=False)
    lon: float = Field(allow_inf_nan=False)
    source: Literal["open-meteo"] = "open-meteo"
    fetched_at: dt.datetime
    stale: bool
    days: list[DayOut]

    @field_validator("fetched_at")
    @classmethod
    def fetched_at_has_a_zone(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at needs a time zone")
        return value

    @field_serializer("fetched_at")
    def fetched_at_in_utc_to_the_second(self, value: dt.datetime) -> str:
        # The format has no fractional seconds, so microseconds are dropped (cut off, not rounded).
        return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
