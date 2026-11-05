import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
EAST_BLOCK = "d9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003"
WEST_BLOCK = "e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004"
GREENHOUSE = "f1c6a4e3-7051-4d8c-9e55-4a9b6c025005"
DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
EAST_FARM = "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

VALID_BODY = {
    "farm_id": DEMO_COOPERATIVE,
    "name": "South block",
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


def test_create_plot_returns_201_with_id_and_sent_fields(client: TestClient) -> None:
    response = client.post("/v1/plots", json=VALID_BODY)

    assert response.status_code == 201
    assert response.json() == {"id": response.json()["id"], **VALID_BODY}


def test_created_plot_can_be_read_back(client: TestClient) -> None:
    created = client.post("/v1/plots", json=VALID_BODY).json()

    response = client.get(f"/v1/plots/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_create_plot_saves_name_stripped_of_spaces(client: TestClient) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, "name": "  South block  "})

    assert response.status_code == 201
    assert response.json()["name"] == "South block"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("area_m2", 0),
        ("area_m2", -1),
        ("row_spacing_m", 0),
        ("emitter_spacing_m", 0),
        ("lat", 90.1),
        ("lat", -90.1),
        ("lon", 180.1),
        ("lon", -180.1),
        ("name", ""),
        ("name", "   "),
        ("planting_date", TOMORROW),
        ("planting_date", "2026-3-1"),
        ("planting_date", "20260301"),
        ("planting_date", "2026-02-30"),
        ("planting_date", "not-a-date"),
    ],
)
def test_create_plot_with_invalid_field_returns_422(client: TestClient, field: str, value: object) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, field: value})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"


def test_create_plot_with_missing_field_returns_422(client: TestClient) -> None:
    body = {key: value for key, value in VALID_BODY.items() if key != "lat"}

    response = client.post("/v1/plots", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


def test_create_plot_with_infinite_area_returns_422(client: TestClient) -> None:
    raw = json.dumps(VALID_BODY).replace('"area_m2": 1000', '"area_m2": 1e999')

    response = client.post("/v1/plots", content=raw, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lat", 90),
        ("lat", -90),
        ("lon", 180),
        ("lon", -180),
        ("planting_date", TODAY),
    ],
)
def test_create_plot_at_boundary_value_returns_201(client: TestClient, field: str, value: object) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, field: value})

    assert response.status_code == 201


def test_unknown_farm_returns_404_problem_json(client: TestClient) -> None:
    body = {**VALID_BODY, "farm_id": "00000000-0000-0000-0000-000000000000"}

    response = client.post("/v1/plots", json=body)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Farm not found"


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("crop_id", "potato", "Unknown crop"),
        ("soil_id", "gravel", "Unknown soil"),
        ("emitter_id", "dripnet-pc-9.9", "Unknown emitter"),
    ],
)
def test_unknown_catalogue_id_returns_422_problem_json(
    client: TestClient, field: str, value: str, detail: str
) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, field: value})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"
    assert response.json()["detail"] == detail


def test_rejected_request_does_not_add_a_plot(client: TestClient) -> None:
    client.post("/v1/plots", json={**VALID_BODY, "crop_id": "potato"})

    response = client.get("/v1/plots")

    assert len(response.json()) == 4


def test_duplicate_name_on_same_farm_returns_409(client: TestClient) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, "name": "North block"})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["detail"] == "Plot name already exists in this farm"


def test_duplicate_name_with_spaces_returns_409(client: TestClient) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, "name": " North block "})

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_same_name_on_another_farm_returns_201(client: TestClient) -> None:
    response = client.post("/v1/plots", json={**VALID_BODY, "farm_id": EAST_FARM, "name": "North block"})

    assert response.status_code == 201


def test_patch_area_returns_full_plot_with_only_area_changed(client: TestClient) -> None:
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()

    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"area_m2": 1200})

    assert response.status_code == 200
    assert response.json() == {**before, "area_m2": 1200}
    assert client.get(f"/v1/plots/{NORTH_BLOCK}").json() == response.json()


def test_patch_with_empty_body_returns_200_and_plot_unchanged(client: TestClient) -> None:
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()

    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={})

    assert response.status_code == 200
    assert response.json() == before


def test_patch_unknown_plot_returns_404_problem_json(client: TestClient) -> None:
    response = client.patch("/v1/plots/00000000-0000-0000-0000-000000000000", json={"area_m2": 1200})

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Plot not found"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("area_m2", 0),
        ("row_spacing_m", 0),
        ("emitter_spacing_m", 0),
        ("lat", 90.1),
        ("lon", 180.1),
        ("name", "   "),
        ("planting_date", TOMORROW),
        ("planting_date", "20260301"),
    ],
)
def test_patch_with_invalid_field_returns_422(client: TestClient, field: str, value: object) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={field: value})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


ALL_FIELDS = [
    "farm_id",
    "name",
    "area_m2",
    "crop_id",
    "planting_date",
    "soil_id",
    "row_spacing_m",
    "emitter_spacing_m",
    "emitter_id",
    "lat",
    "lon",
]


@pytest.mark.parametrize("field", ALL_FIELDS)
def test_patch_with_null_field_returns_422(client: TestClient, field: str) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={field: None})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("crop_id", "potato", "Unknown crop"),
        ("soil_id", "gravel", "Unknown soil"),
        ("emitter_id", "dripnet-pc-9.9", "Unknown emitter"),
    ],
)
def test_patch_with_unknown_catalogue_id_returns_422(
    client: TestClient, field: str, value: str, detail: str
) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={field: value})

    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_patch_with_unknown_farm_returns_404(client: TestClient) -> None:
    response = client.patch(
        f"/v1/plots/{NORTH_BLOCK}", json={"farm_id": "00000000-0000-0000-0000-000000000000"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Farm not found"


def test_patch_name_taken_in_same_farm_returns_409_and_plot_unchanged(client: TestClient) -> None:
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()

    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"name": "East block"})

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert client.get(f"/v1/plots/{NORTH_BLOCK}").json() == before


def test_patch_with_own_name_returns_200(client: TestClient) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"name": "North block"})

    assert response.status_code == 200


def test_patch_farm_moves_plot_to_another_farm(client: TestClient) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"farm_id": EAST_FARM})

    assert response.status_code == 200
    moved = client.get("/v1/plots", params={"farm_id": EAST_FARM}).json()
    assert NORTH_BLOCK in [plot["id"] for plot in moved]


def test_patch_farm_and_name_taken_in_new_farm_returns_409(client: TestClient) -> None:
    response = client.patch(
        f"/v1/plots/{NORTH_BLOCK}", json={"farm_id": EAST_FARM, "name": "West block"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_patch_ignores_id_in_body(client: TestClient) -> None:
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"id": EAST_BLOCK, "area_m2": 1200})

    assert response.status_code == 200
    assert response.json()["id"] == NORTH_BLOCK


def test_delete_plot_returns_204_with_empty_body(client: TestClient) -> None:
    response = client.delete(f"/v1/plots/{NORTH_BLOCK}")

    assert response.status_code == 204
    assert response.content == b""


def test_deleted_plot_returns_404_on_get(client: TestClient) -> None:
    client.delete(f"/v1/plots/{NORTH_BLOCK}")

    response = client.get(f"/v1/plots/{NORTH_BLOCK}")

    assert response.status_code == 404


def test_list_after_delete_has_the_other_three_plots(client: TestClient) -> None:
    client.delete(f"/v1/plots/{NORTH_BLOCK}")

    response = client.get("/v1/plots")

    assert [plot["id"] for plot in response.json()] == [EAST_BLOCK, WEST_BLOCK, GREENHOUSE]


def test_deleting_the_same_plot_twice_returns_404_the_second_time(client: TestClient) -> None:
    client.delete(f"/v1/plots/{NORTH_BLOCK}")

    response = client.delete(f"/v1/plots/{NORTH_BLOCK}")

    assert response.status_code == 404


def test_delete_unknown_plot_returns_404_problem_json(client: TestClient) -> None:
    response = client.delete("/v1/plots/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Plot not found"


def test_delete_both_plots_of_a_farm_then_the_farm_returns_204(client: TestClient) -> None:
    client.delete(f"/v1/plots/{WEST_BLOCK}")
    client.delete(f"/v1/plots/{GREENHOUSE}")

    response = client.delete(f"/v1/farms/{EAST_FARM}")

    assert response.status_code == 204
