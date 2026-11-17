"""The API key must be in no log, no error body and no traceback chain, end to end."""

import logging
import traceback
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import forecast_service
from config import ConfigError, Settings, load_settings
from main import create_app
from tests.fakes import FakeClock
from tests.test_service_rules import NOON

KEY = "SECRET-KEY-task12-abc123"
QUERY = "/v1/forecast?lat=31.25&lon=34.79&days=3"


def leaking(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"cannot reach https://api.example.com/v1/forecast?apikey={KEY}")


def key_settings() -> Settings:
    return Settings(PROVIDER_BASE_URL="https://api.example.com/v1/forecast", PROVIDER_API_KEY=KEY)


def chain_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_the_key_is_in_no_log_error_body_or_traceback_chain(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(key_settings(), transport=httpx.MockTransport(leaking), clock=FakeClock(NOON))
    seen: list[str] = []
    with caplog.at_level(logging.DEBUG):  # every logger, httpx and httpcore included
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.NOTSET)  # as if nobody had silenced them
        with TestClient(app) as client:
            failed = client.get(QUERY)  # the provider fails with the key in the exception text
            assert failed.status_code == 503
            seen += [failed.text, str(failed.headers)]

            async def explode(self, cell, days):
                raise RuntimeError(f"bug with {KEY}")

            monkeypatch.setattr(forecast_service.ForecastService, "get", explode)
            crashed = client.get(QUERY)  # a 500 path
            assert crashed.status_code == 500
            seen += [crashed.text, str(crashed.headers)]
    assert KEY not in caplog.text and "apikey" not in caplog.text
    assert all(KEY not in text for text in seen)
    assert "RuntimeError" in caplog.text  # the class is logged, the message is not


def test_settings_repr_and_a_config_error_chain_never_show_the_key() -> None:
    assert KEY not in repr(key_settings()) and KEY not in str(key_settings())
    with pytest.raises(ConfigError) as info:
        load_settings(Path("/nonexistent/.env"))
    assert KEY not in chain_text(info.value)


def test_a_missing_base_url_stops_startup_with_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER_BASE_URL", raising=False)
    monkeypatch.setattr("main.load_settings", lambda: load_settings(Path("/nonexistent/.env")))
    app = create_app()
    with pytest.raises(ConfigError, match="PROVIDER_BASE_URL"):
        with TestClient(app):
            pass
