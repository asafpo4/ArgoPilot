from fastapi.testclient import TestClient

NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
EAST_BLOCK = "d9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003"
WEST_BLOCK = "e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004"
GREENHOUSE = "f1c6a4e3-7051-4d8c-9e55-4a9b6c025005"
DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
EAST_FARM = "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"


def test_list_plots_returns_all_four_seeded_plots(client: TestClient) -> None:
    response = client.get("/v1/plots")

    assert response.status_code == 200
    assert [plot["id"] for plot in response.json()] == [NORTH_BLOCK, EAST_BLOCK, WEST_BLOCK, GREENHOUSE]


def test_list_plots_filtered_by_farm_returns_only_that_farms_plots(client: TestClient) -> None:
    response = client.get("/v1/plots", params={"farm_id": EAST_FARM})

    assert response.status_code == 200
    assert [plot["id"] for plot in response.json()] == [WEST_BLOCK, GREENHOUSE]


def test_list_plots_with_unknown_farm_id_returns_empty_list(client: TestClient) -> None:
    response = client.get("/v1/plots", params={"farm_id": "00000000-0000-0000-0000-000000000000"})

    assert response.status_code == 200
    assert response.json() == []


def test_get_plot_returns_the_twelve_fields_with_seeded_values(client: TestClient) -> None:
    response = client.get(f"/v1/plots/{NORTH_BLOCK}")

    assert response.status_code == 200
    assert response.json() == {
        "id": NORTH_BLOCK,
        "farm_id": DEMO_COOPERATIVE,
        "name": "North block",
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


def test_get_unknown_plot_returns_404_problem_json(client: TestClient) -> None:
    response = client.get("/v1/plots/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Plot not found"
