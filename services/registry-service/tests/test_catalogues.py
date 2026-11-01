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
