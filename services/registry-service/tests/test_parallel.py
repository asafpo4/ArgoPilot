from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"

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
