"""Checks of the upstream answers (spec 4.4). No network, no clock.

Every check works on the decoded JSON. A failed check raises InvalidAnswer
with a rule name only: neither the rule nor the message holds a received value.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from engine import WeatherRow

SOURCE = "open-meteo"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UTC_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")


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
