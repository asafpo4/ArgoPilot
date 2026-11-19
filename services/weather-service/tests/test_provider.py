"""The Open-Meteo provider: one attempt, the strict checks of spec 4.2, a total deadline, a streamed size cap,
and no secrets in logs or failure kinds."""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from fakes import DROP, FakeClock, provider_body
from provider import MAX_BODY_BYTES, Failure, OpenMeteoProvider, ProviderForecast

NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)
TODAY = date(2026, 11, 16)
NODE = (Decimal("48.1"), Decimal("11.6"))
BASE_URL = "https://api.example.com/v1/forecast"
ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"

Handler = Callable[[httpx.Request], Any]


def make_provider(
    handler: Handler,
    *,
    key: str = "",
    timeout: float = 1.0,
    clock: FakeClock | None = None,
    client_class: type[httpx.AsyncClient] = httpx.AsyncClient,
) -> OpenMeteoProvider:
    client = client_class(transport=httpx.MockTransport(handler))
    return OpenMeteoProvider(
        client, base_url=BASE_URL, api_key=key, timeout=timeout, clock=clock or FakeClock(NOW)
    )


def reply(body: object) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode())

    return handler


def raises(error: Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


async def fetch(provider: OpenMeteoProvider, node: tuple[Decimal, Decimal] = NODE) -> ProviderForecast | Failure:
    return await provider.fetch(*node)


def edited(mutate: Callable[[dict[str, Any]], None], **kwargs: Any) -> dict[str, Any]:
    body = provider_body(TODAY, **kwargs)
    mutate(body)
    return body


# A valid answer.


@pytest.mark.anyio
async def test_a_valid_body_gives_seven_rows_and_the_zone() -> None:
    body = provider_body(TODAY, tz="Europe/Berlin", utc_offset_seconds=3600)
    body["daily"][ET0] = [3.123456789012345 + i for i in range(7)]  # type: ignore[index]
    body["daily"][RAIN] = [0.0, 1, 2.5, 0.07, 10.000000000000002, 0.1, 4]  # type: ignore[index]
    result = await fetch(make_provider(reply(body)))
    assert isinstance(result, ProviderForecast)
    assert [row.date for row in result.rows] == [TODAY + timedelta(days=i) for i in range(7)]
    assert [row.et0_mm for row in result.rows] == body["daily"][ET0]  # type: ignore[index]  # unrounded
    assert [row.rain_mm for row in result.rows] == [0.0, 1.0, 2.5, 0.07, 10.000000000000002, 0.1, 4.0]
    assert result.tz == ZoneInfo("Europe/Berlin")


@pytest.mark.anyio
async def test_zeros_and_whole_numbers_are_real_values_and_extra_fields_are_ignored() -> None:
    body = provider_body(TODAY, hourly={"time": []}, something_else=1)
    body["daily"][ET0] = [0, 0.0, 1, 2, 3, 4, 5]  # type: ignore[index]
    body["daily"]["extra_series"] = [1, 2, 3]  # type: ignore[index]
    result = await fetch(make_provider(reply(body)))
    assert isinstance(result, ProviderForecast)
    assert [row.et0_mm for row in result.rows] == [0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


# The request.


@pytest.mark.anyio
async def test_the_request_has_exactly_the_agreed_query_without_a_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(provider_body(TODAY)).encode())

    assert isinstance(await fetch(make_provider(handler)), ProviderForecast)
    (request,) = seen
    assert request.method == "GET"
    assert (request.url.scheme, request.url.host, request.url.path) == ("https", "api.example.com", "/v1/forecast")
    assert dict(request.url.params) == {
        "latitude": "48.1",
        "longitude": "11.6",
        "daily": f"{ET0},{RAIN}",
        "forecast_days": "7",
        "timezone": "auto",
    }


@pytest.mark.anyio
async def test_the_request_carries_the_key_only_when_there_is_one() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(provider_body(TODAY)).encode())

    await fetch(make_provider(handler, key="the-key"))
    assert dict(seen[0].url.params)["apikey"] == "the-key"
    seen.clear()
    await fetch(make_provider(handler, key=""))
    assert "apikey" not in dict(seen[0].url.params)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "node, expected",
    [
        ((Decimal("0.0"), Decimal("-0.1")), ("0.0", "-0.1")),
        ((Decimal("90.0"), Decimal("-180.0")), ("90.0", "-180.0")),
        ((Decimal("-31.3"), Decimal("180.0")), ("-31.3", "180.0")),
    ],
)
async def test_the_node_is_sent_with_one_decimal_and_no_exponent(
    node: tuple[Decimal, Decimal], expected: tuple[str, str]
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(provider_body(TODAY)).encode())

    await fetch(make_provider(handler), node)
    assert (seen[0].url.params["latitude"], seen[0].url.params["longitude"]) == expected


# Failures at the transport and body level.


def status(code: int) -> Handler:
    return lambda request: httpx.Response(code, content=b'{"error": true, "reason": "x"}')


def body_bytes(content: bytes) -> Handler:
    return lambda request: httpx.Response(200, content=content)


TRANSPORT_AND_BODY_FAILURES = [
    ("status 400", status(400), "status 400"),
    ("status 404", status(404), "status 404"),
    ("status 429", status(429), "status 429"),
    ("status 500", status(500), "status 500"),
    ("status 503", status(503), "status 503"),
    ("status 204", lambda request: httpx.Response(204), "status 204"),
    ("html instead of json", body_bytes(b"<html>oops</html>"), "not_json"),
    ("empty body", body_bytes(b""), "not_json"),
    ("invalid utf-8", body_bytes(b"\xff\xfe\xfa\xfb"), "not_json"),
    ("deeply nested json", body_bytes(b"[" * 200_000), "not_json"),
    ("an integer over the digit limit", body_bytes(b'{"daily": 1' + b"0" * 5000 + b"}"), "not_json"),
    ("json array", body_bytes(b"[]"), "invalid not_an_object"),
    ("json number", body_bytes(b"3"), "invalid not_an_object"),
    ("json string", body_bytes(b'"x"'), "invalid not_an_object"),
    ("json null", body_bytes(b"null"), "invalid not_an_object"),
    ("connect error", raises(httpx.ConnectError("boom")), "transport"),
    ("read error", raises(httpx.ReadError("boom")), "transport"),
    ("httpx read timeout", raises(httpx.ReadTimeout("slow")), "timeout"),
    ("httpx pool timeout", raises(httpx.PoolTimeout("full")), "timeout"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("handler, kind", [(h, k) for _, h, k in TRANSPORT_AND_BODY_FAILURES],
                         ids=[i for i, _, _ in TRANSPORT_AND_BODY_FAILURES])
async def test_a_transport_or_body_failure_is_a_failure_with_its_kind(handler: Handler, kind: str) -> None:
    assert await fetch(make_provider(handler)) == Failure(kind)


@pytest.mark.anyio
async def test_a_redirect_is_not_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": BASE_URL + "?moved=1"})
        return httpx.Response(200, content=json.dumps(provider_body(TODAY)).encode())

    assert await fetch(make_provider(handler)) == Failure("status 302")
    assert len(calls) == 1


@pytest.mark.anyio
async def test_an_unexpected_exception_is_not_swallowed() -> None:
    with pytest.raises(RuntimeError):
        await fetch(make_provider(raises(RuntimeError("a bug"))))


# Failures in the content, one rule at a time (spec 4.2).

BIG_INT = 10**400  # a whole number too large for a float


def without(*names: str) -> Callable[[dict[str, Any]], None]:
    """Remove top-level fields after the body is built (`provider_body` always sets tz and the offset)."""

    def mutate(body: dict[str, Any]) -> None:
        for name in names:
            body.pop(name)

    return mutate


def at(series: str, index: int, value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(body: dict[str, Any]) -> None:
        body["daily"][series][index] = value

    return mutate


CONTENT_FAILURES: list[tuple[str, Callable[[], dict[str, Any]], str]] = [
    ("daily missing", lambda: edited(lambda b: b.pop("daily")), "invalid missing_daily"),
    ("daily is not an object", lambda: edited(lambda b: b.update(daily=[])), "invalid missing_daily"),
    ("time missing", lambda: edited(lambda b: b["daily"].pop("time")), "invalid missing_field"),
    ("et0 missing", lambda: edited(lambda b: b["daily"].pop(ET0)), "invalid missing_field"),
    ("rain missing", lambda: edited(lambda b: b["daily"].pop(RAIN)), "invalid missing_field"),
    ("et0 is not a list", lambda: edited(lambda b: b["daily"].update({ET0: "3.1"})), "invalid missing_field"),
    ("six rows", lambda: provider_body(TODAY, rows=6), "invalid wrong_length"),
    ("eight rows", lambda: provider_body(TODAY, rows=8), "invalid wrong_length"),
    ("series of different lengths", lambda: edited(lambda b: b["daily"][ET0].pop()), "invalid wrong_length"),
    ("units: inches", lambda: edited(lambda b: b["daily_units"].update({ET0: "inches"})), "invalid units"),
    ("units: rain in cm", lambda: edited(lambda b: b["daily_units"].update({RAIN: "cm"})), "invalid units"),
    ("units: key missing", lambda: edited(lambda b: b["daily_units"].pop(RAIN)), "invalid units"),
    ("units: object missing", lambda: edited(lambda b: b.pop("daily_units")), "invalid units"),
    ("units: not an object", lambda: edited(lambda b: b.update(daily_units="mm")), "invalid units"),
    ("date: impossible", lambda: edited(at("time", 3, "2026-13-45")), "invalid bad_date"),
    ("date: basic format", lambda: edited(at("time", 3, "20261119")), "invalid bad_date"),
    ("date: not text", lambda: edited(at("time", 3, 20261119)), "invalid bad_date"),
    ("date: empty", lambda: edited(at("time", 3, "")), "invalid bad_date"),
    ("date: with a time", lambda: edited(at("time", 3, "2026-11-19T00:00")), "invalid bad_date"),
    ("date: a gap", lambda: edited(at("time", 3, "2026-11-20")), "invalid date_gap"),
    ("date: repeated", lambda: edited(at("time", 3, "2026-11-18")), "invalid date_gap"),
    ("date: out of order", lambda: edited(lambda b: b["daily"]["time"].reverse()), "invalid date_gap"),
    ("first row yesterday", lambda: provider_body(TODAY - timedelta(days=1)), "invalid first_row_not_today"),
    ("first row tomorrow", lambda: provider_body(TODAY + timedelta(days=1)), "invalid first_row_not_today"),
    *[
        (f"{series} null at {index}", lambda s=series, i=index: edited(at(s, i, None)), "invalid bad_value")
        for series in (ET0, RAIN)
        for index in (0, 3, 6)
    ],
    *[
        (f"{series} {label}", lambda s=series, v=value: edited(at(s, 2, v)), "invalid bad_value")
        for series in (ET0, RAIN)
        for label, value in (("string", "3.1"), ("true", True), ("false", False), ("list", []), ("object", {}))
    ],
    *[
        (f"{series} {label}", lambda s=series, v=value: edited(at(s, 4, v)), "invalid not_finite")
        for series in (ET0, RAIN)
        for label, value in (("NaN", float("nan")), ("Infinity", float("inf")), ("-Infinity", float("-inf")), ("huge integer", BIG_INT))
    ],
    *[
        (f"{series} negative {value}", lambda s=series, v=value: edited(at(s, 1, v)), "invalid negative")
        for series in (ET0, RAIN)
        for value in (-0.1, -1, -1e-300)
    ],
    ("zone unknown, no offset", lambda: edited(without("utc_offset_seconds"), tz="Not/AZone"), "invalid unknown_zone"),
    ("zone missing, no offset", lambda: edited(without("timezone", "utc_offset_seconds")), "invalid unknown_zone"),
    ("zone unknown, offset beyond 18 hours", lambda: provider_body(TODAY, tz="Not/AZone", utc_offset_seconds=65000), "invalid unknown_zone"),
    ("zone unknown, offset is a boolean", lambda: provider_body(TODAY, tz="Not/AZone", utc_offset_seconds=True), "invalid unknown_zone"),
    ("zone unknown, offset is a float", lambda: provider_body(TODAY, tz="Not/AZone", utc_offset_seconds=3600.0), "invalid unknown_zone"),
    ("zone is a path", lambda: edited(without("utc_offset_seconds"), tz="../../etc/passwd"), "invalid unknown_zone"),
    ("zone is a directory", lambda: edited(without("utc_offset_seconds"), tz="Europe"), "invalid unknown_zone"),
    ("zone is not text", lambda: edited(without("utc_offset_seconds"), tz=5), "invalid unknown_zone"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("make_body, kind", [(m, k) for _, m, k in CONTENT_FAILURES], ids=[i for i, _, _ in CONTENT_FAILURES])
async def test_a_content_failure_is_a_failure_with_its_rule_and_never_a_forecast(
    make_body: Callable[[], dict[str, Any]], kind: str
) -> None:
    assert await fetch(make_provider(reply(make_body()))) == Failure(kind)


@pytest.mark.anyio
@pytest.mark.parametrize("series", [ET0, RAIN])
async def test_null_in_the_last_value_is_a_failure_not_a_zero(series: str) -> None:
    # Review Focus 1: the last entry is where a provider is most likely to run out of data.
    result = await fetch(make_provider(reply(edited(at(series, 6, None)))))
    assert not isinstance(result, ProviderForecast)
    assert result == Failure("invalid bad_value")


# Time zones: "today" follows the zone of the point (Review Focus 2).

ZONES = [
    ("Asia/Kolkata", 19800, datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)),
    ("Asia/Kathmandu", 20700, datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)),
    ("Pacific/Kiritimati", 50400, datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)),
    ("America/Los_Angeles", -28800, datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)),
    ("Pacific/Pago_Pago", -39600, datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)),
]


@pytest.mark.anyio
@pytest.mark.parametrize("name, offset, utc_time", ZONES)
async def test_today_follows_the_zone_of_the_point(name: str, offset: int, utc_time: datetime) -> None:
    clock = FakeClock(utc_time)
    local_today = utc_time.astimezone(ZoneInfo(name)).date()
    utc_today = utc_time.date()
    assert local_today != utc_today  # the case is only meaningful if the two dates differ

    good = await fetch(make_provider(reply(provider_body(local_today, tz=name, utc_offset_seconds=offset)), clock=clock))
    assert isinstance(good, ProviderForecast)
    assert good.rows[0].date == local_today
    assert good.tz == ZoneInfo(name)

    wrong_day = await fetch(make_provider(reply(provider_body(utc_today, tz=name, utc_offset_seconds=offset)), clock=clock))
    assert wrong_day == Failure("invalid first_row_not_today")


@pytest.mark.anyio
async def test_an_unknown_zone_name_falls_back_to_the_fixed_offset() -> None:
    clock = FakeClock(datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc))
    body = provider_body(date(2026, 11, 17), tz="Not/AZone", utc_offset_seconds=19800)
    result = await fetch(make_provider(reply(body), clock=clock))
    assert isinstance(result, ProviderForecast)
    assert result.tz.utcoffset(None) == timedelta(seconds=19800)


@pytest.mark.anyio
async def test_the_date_line_gives_different_local_dates() -> None:
    clock = FakeClock(datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))
    east = await fetch(make_provider(reply(provider_body(date(2026, 11, 17), tz="Pacific/Auckland", utc_offset_seconds=46800)), clock=clock))
    west = await fetch(make_provider(reply(provider_body(date(2026, 11, 16), tz="Pacific/Pago_Pago", utc_offset_seconds=-39600)), clock=clock))
    assert isinstance(east, ProviderForecast) and isinstance(west, ProviderForecast)
    assert east.rows[0].date != west.rows[0].date


# The deadline: one total limit around the whole call.


class BlockedBeforeConnecting(httpx.AsyncClient):
    """A client that never gets a connection, as when the pool is full. `send` never returns."""

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.anyio
async def test_a_client_that_blocks_before_connecting_fails_inside_the_deadline() -> None:
    provider = make_provider(reply(provider_body(TODAY)), client_class=BlockedBeforeConnecting, timeout=0.05)
    started = time.monotonic()
    result = await asyncio.wait_for(fetch(provider), timeout=2)  # a guard, so a missing deadline fails and does not hang
    assert result == Failure("timeout")
    assert time.monotonic() - started < 0.5


@pytest.mark.anyio
async def test_a_provider_that_never_answers_fails_inside_the_deadline() -> None:
    async def never(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    started = time.monotonic()
    result = await asyncio.wait_for(fetch(make_provider(never, timeout=0.05)), timeout=2)
    assert result == Failure("timeout")
    assert time.monotonic() - started < 0.5


class SlowStream(httpx.AsyncByteStream):
    """One byte every 10 ms, forever. No gap is long, so only a total deadline can stop it."""

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        while True:
            await asyncio.sleep(0.01)
            yield b" "


@pytest.mark.anyio
async def test_a_body_that_trickles_in_is_cut_by_the_total_deadline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream())

    started = time.monotonic()
    result = await asyncio.wait_for(fetch(make_provider(handler, timeout=0.05)), timeout=2)
    assert result == Failure("timeout")
    assert time.monotonic() - started < 0.5


# The size cap: the body is read as a stream and cut off at the cap (Review Focus 5).

CHUNK = 64 * 1024


class CountingStream(httpx.AsyncByteStream):
    """Chunks of `CHUNK` bytes, `chunks` of them (None for endless). Records the bytes handed to the reader."""

    def __init__(self, chunks: int | None) -> None:
        self.chunks = chunks
        self.consumed_bytes = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        sent = 0
        while self.chunks is None or sent < self.chunks:
            self.consumed_bytes += CHUNK
            sent += 1
            yield b"x" * CHUNK
            await asyncio.sleep(0)


@pytest.mark.anyio
async def test_a_body_over_the_size_cap_is_cut_off_while_it_is_being_read() -> None:
    stream = CountingStream(chunks=128)  # 8 MiB in all
    result = await fetch(make_provider(lambda request: httpx.Response(200, stream=stream), timeout=5))
    assert result == Failure("invalid too_large")
    assert stream.consumed_bytes > MAX_BODY_BYTES  # it read past the cap, to know the body is over it
    assert stream.consumed_bytes <= MAX_BODY_BYTES + CHUNK  # and stopped within one chunk of the cap
    assert stream.consumed_bytes < 128 * CHUNK  # the rest was never read


@pytest.mark.anyio
async def test_an_endless_body_is_stopped_by_the_cap_and_not_by_the_deadline() -> None:
    stream = CountingStream(chunks=None)
    result = await fetch(make_provider(lambda request: httpx.Response(200, stream=stream), timeout=5))
    assert result == Failure("invalid too_large")
    assert stream.consumed_bytes <= MAX_BODY_BYTES + CHUNK


@pytest.mark.anyio
async def test_the_cap_is_one_mebibyte_and_a_body_of_exactly_that_size_is_accepted() -> None:
    assert MAX_BODY_BYTES == 1024 * 1024
    raw = json.dumps(provider_body(TODAY)).encode()
    exactly = raw + b" " * (MAX_BODY_BYTES - len(raw))
    assert len(exactly) == MAX_BODY_BYTES
    result = await fetch(make_provider(lambda request: httpx.Response(200, content=exactly), timeout=5))
    assert isinstance(result, ProviderForecast)


@pytest.mark.anyio
async def test_a_body_one_byte_over_the_cap_is_a_failure() -> None:
    raw = json.dumps(provider_body(TODAY)).encode()
    over = raw + b" " * (MAX_BODY_BYTES + 1 - len(raw))
    assert len(over) == MAX_BODY_BYTES + 1
    result = await fetch(make_provider(lambda request: httpx.Response(200, content=over), timeout=5))
    assert result == Failure("invalid too_large")


@pytest.mark.anyio
async def test_the_cap_counts_the_decoded_body_so_a_compressed_bomb_is_stopped() -> None:
    import gzip

    bomb = gzip.compress(b" " * (MAX_BODY_BYTES * 4))
    assert len(bomb) < MAX_BODY_BYTES // 100  # tiny on the wire, huge once decoded
    handler = lambda request: httpx.Response(200, content=bomb, headers={"Content-Encoding": "gzip"})  # noqa: E731
    result = await fetch(make_provider(handler, timeout=5))
    assert result == Failure("invalid too_large")


# Secrets.


@pytest.fixture
def default_http_loggers():  # type: ignore[no-untyped-def]
    names = ("httpx", "httpcore")
    saved = {name: logging.getLogger(name).level for name in names}
    for name in names:
        logging.getLogger(name).setLevel(logging.NOTSET)
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


KEY = "KEYMARK-9f2c41"


def test_making_a_provider_puts_the_http_loggers_at_warning(default_http_loggers: None) -> None:
    make_provider(reply(provider_body(TODAY)), key=KEY)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


@pytest.mark.anyio
async def test_the_key_is_in_no_log_and_no_failure_kind(
    caplog: pytest.LogCaptureFixture, default_http_loggers: None
) -> None:
    leaking = raises(httpx.ConnectError(f"cannot reach https://api.example.com/v1/forecast?apikey={KEY}"))
    with caplog.at_level(logging.DEBUG):  # every logger, including httpx and httpcore
        failed = await fetch(make_provider(leaking, key=KEY))
        succeeded = await fetch(make_provider(reply(provider_body(TODAY)), key=KEY))
    assert failed == Failure("transport")  # the kind is a fixed word, never the exception text
    assert isinstance(succeeded, ProviderForecast)
    assert KEY not in caplog.text
    assert "apikey" not in caplog.text
