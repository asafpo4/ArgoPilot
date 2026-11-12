import json
import re

import pytest
from fastapi.testclient import TestClient

from main import app

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"

VALID_PLOT_FIELDS = {
    "farm_id": DEMO_COOPERATIVE,
    "name": "Nul block",
    "area_m2": 1000,
    "crop_id": "tomato",
    "planting_date": "2026-03-01",
    "soil_id": "loam",
    "row_spacing_m": 1.5,
    "emitter_spacing_m": 0.4,
    "emitter_id": "dripnet-pc-1.0",
    "lat": 31.25,
    "lon": 34.79,
}


def test_nul_lookup_values_keep_todays_answers(client: TestClient) -> None:
    sites = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/v1"):
            continue
        for method, operation in operations.items():
            parameters = operation.get("parameters", [])
            has_path_id = any(p["in"] == "path" for p in parameters)
            query_ids = [p["name"] for p in parameters if p["in"] == "query" and p["name"].endswith("_id")]
            if has_path_id or query_ids:
                sites.append((method.upper(), path, query_ids))

    assert len(sites) == 10

    for method, path, query_ids in sites:
        url = re.sub(r"\{[^}]+\}", "a%00b", path)
        if query_ids:
            url += "?" + "&".join(f"{name}=a%00b" for name in query_ids)
        kwargs = {"json": {"name": "x"}} if method == "PATCH" else {}

        response = client.request(method, url, **kwargs)

        if query_ids:
            assert response.status_code == 200, (method, url)
            assert response.json() == [], (method, url)
        else:
            assert response.status_code == 404, (method, url)


@pytest.mark.parametrize(
    "method, path, field",
    [
        ("POST", "/v1/farms", "name"),
        ("PATCH", f"/v1/farms/{DEMO_COOPERATIVE}", "name"),
    ]
    + [
        (method, path, field)
        for field in ("name", "farm_id", "crop_id", "soil_id", "emitter_id")
        for method, path in (("POST", "/v1/plots"), ("PATCH", f"/v1/plots/{NORTH_BLOCK}"))
    ],
)
def test_nul_in_body_text_returns_422(client: TestClient, method: str, path: str, field: str) -> None:
    # The JSON text holds the six characters \u0000.
    fields = {"name": "Nul block"} if path == "/v1/farms" or "/v1/farms/" in path else {}
    if path.startswith("/v1/plots") and method == "POST":
        fields = dict(VALID_PLOT_FIELDS)
    fields[field] = "@@NUL@@"
    raw = json.dumps(fields).replace("@@NUL@@", "\\u0000")

    response = client.request(method, path, content=raw, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"
    assert response.json()["detail"] == "Text contains invalid characters"
