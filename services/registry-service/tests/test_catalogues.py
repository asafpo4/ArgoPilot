from fastapi.testclient import TestClient


def test_list_crops_returns_both_seeded_crops(client: TestClient) -> None:
    response = client.get("/v1/crops")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "bell-pepper", "name": "Bell pepper"},
        {"id": "tomato", "name": "Tomato"},
    ]


def test_get_crop_returns_the_requested_crop(client: TestClient) -> None:
    response = client.get("/v1/crops/tomato")

    assert response.status_code == 200
    assert response.json() == {"id": "tomato", "name": "Tomato"}


def test_get_unknown_crop_returns_404(client: TestClient) -> None:
    response = client.get("/v1/crops/potato")

    assert response.status_code == 404


def test_list_soils_returns_all_three_soils(client: TestClient) -> None:
    response = client.get("/v1/soils")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "clay-loam", "name": "Clay loam", "available_water_mm_per_m": 200},
        {"id": "loam", "name": "Loam", "available_water_mm_per_m": 175},
        {"id": "sand", "name": "Sand", "available_water_mm_per_m": 83},
    ]


def test_get_soil_returns_the_requested_soil(client: TestClient) -> None:
    response = client.get("/v1/soils/loam")

    assert response.status_code == 200
    assert response.json() == {"id": "loam", "name": "Loam", "available_water_mm_per_m": 175}


def test_get_unknown_soil_returns_404(client: TestClient) -> None:
    response = client.get("/v1/soils/gravel")

    assert response.status_code == 404
