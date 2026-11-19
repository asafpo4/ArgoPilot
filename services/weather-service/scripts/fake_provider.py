"""A local stand-in for Open-Meteo, for the p95 measurement. Not part of the service.

It answers GET /v1/forecast with a valid provider-shaped body whose dates start at today's date in the zone
it reports (UTC), and it counts every forecast call. GET /calls returns the count as JSON.

Run: uv run python scripts/fake_provider.py --host 127.0.0.1 --port 9101
"""

import argparse
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROWS = 7
ET0 = "et0_fao_evapotranspiration"
RAIN = "precipitation_sum"


class Counter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.value = 0

    def bump(self) -> None:
        with self._lock:
            self.value += 1


def make_body(latitude: float, longitude: float) -> dict[str, object]:
    today = datetime.now(timezone.utc).date()  # the zone this server reports: UTC, offset 0
    times = [(today + timedelta(days=i)).isoformat() for i in range(ROWS)]
    return {
        "latitude": latitude,
        "longitude": longitude,
        "generationtime_ms": 0.5,
        "utc_offset_seconds": 0,
        "timezone": "UTC",
        "timezone_abbreviation": "GMT",
        "elevation": 500.0,
        "daily_units": {"time": "iso8601", ET0: "mm", RAIN: "mm"},
        "daily": {
            "time": times,
            ET0: [round(3.0 + 0.1 * i, 1) for i in range(ROWS)],
            RAIN: [round(1.5 * (i % 2), 1) for i in range(ROWS)],
        },
    }


def make_handler(counter: Counter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (the name http.server requires)
            parts = urlsplit(self.path)
            if parts.path == "/calls":
                self._send(200, {"calls": counter.value})
            elif parts.path == "/v1/forecast":
                counter.bump()
                query = parse_qs(parts.query)
                try:
                    latitude = float(query.get("latitude", ["0"])[0])
                    longitude = float(query.get("longitude", ["0"])[0])
                except ValueError:
                    self._send(400, {"error": "bad coordinates"})
                    return
                self._send(200, make_body(latitude, longitude))
            else:
                self._send(404, {"error": "not found"})

        def _send(self, status: int, payload: dict[str, object]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:
            return  # keep the terminal quiet; the counter is the record

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9101)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(Counter()))
    print(f"fake provider on http://{args.host}:{args.port}/v1/forecast, count at /calls", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
