import pytest
from fastapi.testclient import TestClient

import plots
from conftest import TestDatabase

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
DEMO_FARMS = [DEMO_COOPERATIVE, "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"]

VALID_BODY = {
    "farm_id": DEMO_COOPERATIVE,
    "name": "Parity block",
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


def test_integrity_violation_then_reference_check_gives_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_check = plots.check_references
    calls: list[int] = []

    def first_call_does_nothing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return None
        return real_check(*args, **kwargs)

    monkeypatch.setattr(plots, "check_references", first_call_does_nothing)

    response = client.post("/v1/plots", json={**VALID_BODY, "farm_id": "no-such-farm"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["detail"] == "Farm not found"
    assert len(calls) == 2


def test_duplicate_plot_name_gives_409_on_create_and_update(client: TestClient) -> None:
    first = client.post("/v1/plots", json=VALID_BODY)
    assert first.status_code == 201

    duplicate = client.post("/v1/plots", json=VALID_BODY)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"
    assert duplicate.json()["detail"] == "Plot name already exists in this farm"

    other = client.post("/v1/plots", json={**VALID_BODY, "name": "Other parity block"})
    assert other.status_code == 201
    update = client.patch(f"/v1/plots/{other.json()['id']}", json={"name": VALID_BODY["name"]})
    assert update.status_code == 409
    assert update.json()["code"] == "CONFLICT"

    assert client.get("/v1/plots").status_code == 200


def test_farm_delete_with_plots_gives_409(client: TestClient) -> None:
    response = client.delete(f"/v1/farms/{DEMO_COOPERATIVE}")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["detail"] == "Farm has plots"


def test_list_order_is_byte_order(client: TestClient, database: TestDatabase) -> None:
    new_ids = ["a-1", "A-2", "a_3", "B-1", "b-2"]
    conn = database.connect()
    try:
        for farm_id in new_ids:
            conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", (farm_id, f"Farm {farm_id}"))
        conn.commit()
    finally:
        conn.close()

    response = client.get("/v1/farms")

    assert response.status_code == 200
    ids = [farm["id"] for farm in response.json()]
    assert ids == sorted(new_ids + DEMO_FARMS, key=str.encode)


@pytest.mark.parametrize("name", ["חווה 🌱", "x" * 10_000])
def test_unicode_and_long_names_round_trip(client: TestClient, name: str) -> None:
    created = client.post("/v1/farms", json={"name": name})
    assert created.status_code == 201
    assert created.json()["name"] == name

    fetched = client.get(f"/v1/farms/{created.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == name


def test_sql_metacharacters_are_plain_text(client: TestClient) -> None:
    name = "'; DROP TABLE farms; --"
    created = client.post("/v1/farms", json={"name": name})
    assert created.status_code == 201
    assert created.json()["name"] == name
    assert client.get(f"/v1/farms/{created.json()['id']}").json()["name"] == name

    assert client.get("/v1/farms/%27%3B%20DROP%20TABLE%20farms%3B%20--").status_code == 404

    listed = client.get("/v1/farms")
    assert listed.status_code == 200
    assert set(DEMO_FARMS) <= {farm["id"] for farm in listed.json()}


@pytest.mark.parametrize("area", [0.1, 1e-7, 123456789.123456789])
def test_floats_round_trip_exactly(client: TestClient, area: float) -> None:
    created = client.post("/v1/plots", json={**VALID_BODY, "name": f"Area {area!r}", "area_m2": area})
    assert created.status_code == 201
    assert created.json()["area_m2"] == area

    fetched = client.get(f"/v1/plots/{created.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["area_m2"] == area


def test_connection_uses_expected_settings(database: TestDatabase) -> None:
    if database.backend != "postgres":
        pytest.skip("PostgreSQL only")
    conn = database.connect()
    try:
        lock_timeout = conn.execute("SHOW lock_timeout").fetchone()
        search_path = conn.execute("SHOW search_path").fetchone()
    finally:
        conn.close()

    assert lock_timeout["lock_timeout"] == "5s"
    assert search_path["search_path"].startswith("test_")
