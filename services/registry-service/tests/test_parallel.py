from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"

VALID_BODY = {
    "farm_id": DEMO_COOPERATIVE,
    "name": "Parallel block",
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


def test_200_parallel_list_requests_all_return_200(client: TestClient) -> None:
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: client.get("/v1/plots").status_code, range(200)))

    assert statuses == [200] * 200


def test_20_parallel_creates_with_same_name_give_one_201_and_19_409(client: TestClient) -> None:
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: client.post("/v1/plots", json=VALID_BODY).status_code, range(20)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 19


def test_20_parallel_deletes_of_one_plot_give_one_204_and_19_404(client: TestClient) -> None:
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: client.delete(f"/v1/plots/{NORTH_BLOCK}").status_code, range(20)))

    assert statuses.count(204) == 1
    assert statuses.count(404) == 19


def test_farm_delete_racing_plot_creates_gives_only_expected_statuses(client: TestClient) -> None:
    farm_id = client.post("/v1/farms", json={"name": "Racing farm"}).json()["id"]

    def delete_farm() -> int:
        return client.delete(f"/v1/farms/{farm_id}").status_code

    def create_plot(index: int) -> int:
        body = {**VALID_BODY, "farm_id": farm_id, "name": f"Race block {index}"}
        return client.post("/v1/plots", json=body).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(delete_farm)] + [pool.submit(create_plot, i) for i in range(19)]
        statuses = [future.result() for future in futures]

    assert set(statuses) <= {201, 204, 404, 409}
