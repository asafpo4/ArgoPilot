"""The request text rules (spec 2.1) and the response models (spec 2.2)."""

import datetime as dt
from decimal import Decimal, InvalidOperation

import pytest
from pydantic import ValidationError

import schemas
from errors import RequestError
from schemas import DayOut, ForecastOut, ForecastQuery, parse_forecast_query


def parse(lat: str = "31.25", lon: str = "34.79", days: str = "3", extra: tuple = ()) -> ForecastQuery:
    return parse_forecast_query([("lat", lat), ("lon", lon), ("days", days), *extra])


def problems_of(**kwargs: str) -> list[tuple[str, str]]:
    with pytest.raises(RequestError) as info:
        parse(**kwargs)
    return info.value.problems


# The tables of spec 2.1, one parametrized case per row.

DAYS_ACCEPTED = ["1", "2", "3", "4", "5", "6", "7"]
DAYS_REJECTED = [
    "0", "8", "9", "10", "07", "+3", "-3", " 3", "3 ", "3.0", "3.5", "3e0",
    "٣",  # Arabic-Indic digit three
    "３",  # full-width digit three
    "",
    "3\n", "\t3", "3\x00",  # added: characters a loose pattern would let through
]

LAT_ACCEPTED = [
    "0", "-0", "+0", "31.25", "+31.25", "-90", "90", "90.0", "-89.9999",
    "1e-05", "1E-5", "-1.5e1", "9e0", "1e-999",
    "0." + "0" * 30,  # added: exactly 32 characters
]
LAT_REJECTED = [
    "90.0000000000000001", "-90.1", "91", "1e2", "1e999",
    "1e1000", "1e-1000",
    "1e" + "9" * 25, "1e-" + "9" * 25,
    "1_0", " 1", "1 ", "0x1A", "nan", "NaN", "inf", "-inf", "infinity",
    "١٢", "１２",
    ".5", "5.", "1e", "1e+", "--1", "1.2.3", "1,5", "",
    "0." + "0" * 31,  # a 33-character number: valid text, one character too long
    "31.25\n", "\t31.25", "31.25\x00",  # added
]

LON_ACCEPTED = ["0", "-180", "180", "180.0", "-179.99", "+34.79", "1e-05", "1.8e2", "1e-999", "0." + "0" * 30]
LON_REJECTED = [
    "180.0000000000001", "-180.1", "181", "1e3",
    "1e1000", "1e-1000",
    "1e" + "9" * 25, "1e-" + "9" * 25,
    "1_0", " 1", "1 ", "0x1A", "nan", "inf", "-inf", "１２", ".5", "5.", "",
    "0." + "0" * 31,
    "34.79\n", "\t34.79", "34.79\x00",
]


@pytest.mark.parametrize("text", DAYS_ACCEPTED)
def test_days_accepted(text: str) -> None:
    assert parse(days=text).days == int(text)


@pytest.mark.parametrize("text", DAYS_REJECTED)
def test_days_rejected(text: str) -> None:
    assert [name for name, _ in problems_of(days=text)] == ["days"]


@pytest.mark.parametrize("text", LAT_ACCEPTED)
def test_lat_accepted_gives_the_exact_decimal(text: str) -> None:
    result = parse(lat=text).lat
    assert result == Decimal(text)
    assert result.as_tuple() == Decimal(text).as_tuple()


@pytest.mark.parametrize("text", LAT_REJECTED)
def test_lat_rejected(text: str) -> None:
    assert [name for name, _ in problems_of(lat=text)] == ["lat"]


@pytest.mark.parametrize("text", LON_ACCEPTED)
def test_lon_accepted_gives_the_exact_decimal(text: str) -> None:
    result = parse(lon=text).lon
    assert result == Decimal(text)
    assert result.as_tuple() == Decimal(text).as_tuple()


@pytest.mark.parametrize("text", LON_REJECTED)
def test_lon_rejected(text: str) -> None:
    assert [name for name, _ in problems_of(lon=text)] == ["lon"]


def test_the_accepted_query_has_the_three_values() -> None:
    assert parse("31.25", "34.79", "7") == ForecastQuery(Decimal("31.25"), Decimal("34.79"), 7)


# Missing, repeated, extra, and several problems together.


@pytest.mark.parametrize("name", ["lat", "lon", "days"])
def test_a_missing_parameter_is_a_problem_for_that_field(name: str) -> None:
    items = [(k, v) for k, v in [("lat", "1"), ("lon", "1"), ("days", "1")] if k != name]
    with pytest.raises(RequestError) as info:
        parse_forecast_query(items)
    assert info.value.problems == [(name, "is required")]


@pytest.mark.parametrize("name", ["lat", "lon", "days"])
def test_a_repeated_parameter_is_a_problem_even_when_both_values_are_valid(name: str) -> None:
    items = [("lat", "1"), ("lon", "1"), ("days", "1"), (name, "2")]
    with pytest.raises(RequestError) as info:
        parse_forecast_query(items)
    assert info.value.problems == [(name, "must appear exactly once")]


def test_an_empty_query_reports_all_three_fields() -> None:
    with pytest.raises(RequestError) as info:
        parse_forecast_query([])
    assert [name for name, _ in info.value.problems] == ["lat", "lon", "days"]


def test_every_problem_is_reported_in_one_error_in_field_order() -> None:
    items = [("days", "1"), ("days", "2"), ("lat", "91")]
    with pytest.raises(RequestError) as info:
        parse_forecast_query(items)
    assert [name for name, _ in info.value.problems] == ["lat", "lon", "days"]


def test_other_parameters_are_ignored() -> None:
    result = parse(extra=(("foo", "bar"), ("Lat", "not a number"), ("units", "")))
    assert result == ForecastQuery(Decimal("31.25"), Decimal("34.79"), 3)


def test_a_conversion_error_is_a_request_error_not_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    # The pattern already keeps odd exponents out. This is the second line of defence.
    def broken(text: str) -> Decimal:
        raise InvalidOperation("conversion failed")

    monkeypatch.setattr(schemas, "_to_decimal", broken)
    # Both coordinates go through the broken conversion, so both are reported, and nothing escapes as a 500.
    assert [name for name, _ in problems_of(lat="31.25", lon="34.79")] == ["lat", "lon"]


def test_a_message_never_echoes_the_value() -> None:
    for kwargs in ({"lat": "LEAKMARK-lat"}, {"lon": "LEAKMARK-lon"}, {"days": "LEAKMARK-days"}):
        assert all("LEAKMARK" not in message for _, message in problems_of(**kwargs))


# The response models (spec 2.2).

WHEN = dt.datetime(2026, 11, 16, 9, 30, 12, tzinfo=dt.timezone.utc)


def forecast(**overrides: object) -> ForecastOut:
    fields: dict[str, object] = {
        "lat": 31.25,
        "lon": 34.79,
        "fetched_at": WHEN,
        "stale": False,
        "days": [DayOut(date=dt.date(2026, 11, 16), et0_mm=3.1, rain_mm=0.0)],
    }
    fields.update(overrides)
    return ForecastOut(**fields)  # type: ignore[arg-type]


def test_response_has_exactly_the_agreed_keys() -> None:
    body = forecast().model_dump(mode="json")
    assert set(body) == {"lat", "lon", "source", "fetched_at", "stale", "days"}
    assert set(body["days"][0]) == {"date", "et0_mm", "rain_mm"}
    assert body["days"][0] == {"date": "2026-11-16", "et0_mm": 3.1, "rain_mm": 0.0}


def test_extra_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        forecast(precipitation_sum=1.0)
    with pytest.raises(ValidationError):
        DayOut(date=dt.date(2026, 11, 16), et0_mm=1.0, rain_mm=0.0, extra=1)  # type: ignore[call-arg]


@pytest.mark.parametrize("missing", ["date", "et0_mm", "rain_mm"])
def test_no_weather_field_of_a_row_has_a_default(missing: str) -> None:
    fields = {"date": dt.date(2026, 11, 16), "et0_mm": 1.0, "rain_mm": 0.0}
    del fields[missing]
    with pytest.raises(ValidationError):
        DayOut(**fields)


@pytest.mark.parametrize("name", ["lat", "lon", "fetched_at", "stale", "days"])
def test_no_field_of_the_answer_has_a_default_except_the_fixed_source(name: str) -> None:
    assert ForecastOut.model_fields[name].is_required()


def test_source_is_open_meteo() -> None:
    assert forecast().source == "open-meteo"
    assert forecast().model_dump(mode="json")["source"] == "open-meteo"
    with pytest.raises(ValidationError):
        forecast(source="somewhere-else")


def test_fetched_at_is_utc_with_z_to_the_second() -> None:
    assert forecast().model_dump(mode="json")["fetched_at"] == "2026-11-16T09:30:12Z"
    assert '"fetched_at":"2026-11-16T09:30:12Z"' in forecast().model_dump_json()


def test_fetched_at_drops_the_microseconds_and_converts_to_utc() -> None:
    with_micro = dt.datetime(2026, 11, 16, 9, 30, 12, 999999, tzinfo=dt.timezone.utc)
    assert forecast(fetched_at=with_micro).model_dump(mode="json")["fetched_at"] == "2026-11-16T09:30:12Z"
    plus_two = dt.datetime(2026, 11, 16, 11, 30, 12, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert forecast(fetched_at=plus_two).model_dump(mode="json")["fetched_at"] == "2026-11-16T09:30:12Z"


def test_a_time_without_a_zone_is_refused() -> None:
    with pytest.raises(ValidationError):
        forecast(fetched_at=dt.datetime(2026, 11, 16, 9, 30, 12))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_number_that_is_not_finite_is_refused(bad: float) -> None:
    with pytest.raises(ValidationError):
        DayOut(date=dt.date(2026, 11, 16), et0_mm=bad, rain_mm=0.0)
    with pytest.raises(ValidationError):
        DayOut(date=dt.date(2026, 11, 16), et0_mm=1.0, rain_mm=bad)
