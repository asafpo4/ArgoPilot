from fastapi.testclient import TestClient


def test_list_farms_returns_both_seeded_farms(client: TestClient) -> None:
    response = client.get("/v1/farms")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004", "name": "East farm"},
        {"id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", "name": "Demo cooperative"},
    ]


def test_get_farm_returns_the_requested_farm(client: TestClient) -> None:
    response = client.get("/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001")

    assert response.status_code == 200
    assert response.json() == {
        "id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
        "name": "Demo cooperative",
    }


def test_get_unknown_farm_returns_404_not_found(client: TestClient) -> None:
    response = client.get("/v1/farms/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Farm not found"
