import pytest
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


def test_create_farm_returns_201_with_id_and_name(client: TestClient) -> None:
    response = client.post("/v1/farms", json={"name": "North farm"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name"}
    assert body["name"] == "North farm"


def test_created_farm_can_be_read_back(client: TestClient) -> None:
    created = client.post("/v1/farms", json={"name": "North farm"}).json()

    response = client.get(f"/v1/farms/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_create_farm_strips_spaces_around_name(client: TestClient) -> None:
    response = client.post("/v1/farms", json={"name": "  North farm  "})

    assert response.status_code == 201
    assert response.json()["name"] == "North farm"


@pytest.mark.parametrize("payload", [{"name": ""}, {"name": "   "}, {}])
def test_create_farm_with_blank_or_missing_name_returns_422(
    client: TestClient, payload: dict[str, str]
) -> None:
    response = client.post("/v1/farms", json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"


def test_rename_farm_returns_200_and_get_shows_new_name(client: TestClient) -> None:
    response = client.patch(
        "/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", json={"name": "Renamed farm"}
    )

    assert response.status_code == 200
    assert response.json() == {"id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", "name": "Renamed farm"}
    after = client.get("/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001")
    assert after.json()["name"] == "Renamed farm"


def test_rename_one_farm_leaves_the_other_farm_unchanged(client: TestClient) -> None:
    client.patch("/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", json={"name": "Renamed farm"})

    response = client.get("/v1/farms/a9c1e4b2-6f70-4d8e-a144-3f8b5c904004")

    assert response.json()["name"] == "East farm"


def test_patch_strips_spaces_around_new_name(client: TestClient) -> None:
    response = client.patch(
        "/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", json={"name": "  Renamed farm  "}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed farm"


@pytest.mark.parametrize("payload", [{"name": ""}, {"name": "   "}, {"name": None}])
def test_patch_with_blank_or_null_name_returns_422(
    client: TestClient, payload: dict[str, str | None]
) -> None:
    response = client.patch("/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


def test_patch_with_empty_body_returns_200_and_farm_unchanged(client: TestClient) -> None:
    response = client.patch("/v1/farms/b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", json={})

    assert response.status_code == 200
    assert response.json() == {"id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", "name": "Demo cooperative"}


def test_patch_unknown_farm_returns_404_not_found(client: TestClient) -> None:
    response = client.patch(
        "/v1/farms/00000000-0000-0000-0000-000000000000", json={"name": "Renamed farm"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
