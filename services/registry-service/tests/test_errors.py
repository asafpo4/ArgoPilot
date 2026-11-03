from fastapi.testclient import TestClient


def test_unknown_crop_returns_problem_json_not_found(client: TestClient) -> None:
    response = client.get("/v1/crops/potato")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Crop not found",
        "code": "NOT_FOUND",
    }


def test_unknown_route_returns_problem_json(client: TestClient) -> None:
    response = client.get("/v1/nothing-here")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"


def test_delete_on_catalogue_returns_405_with_allow_header(client: TestClient) -> None:
    response = client.delete("/v1/crops/tomato")

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert "allow" in response.headers
    assert response.json()["code"] == "VALIDATION"


def test_database_unavailable_returns_503_with_retry_after(unavailable_client: TestClient) -> None:
    response = unavailable_client.get("/v1/crops")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["retry-after"] == "5"
    assert response.json()["code"] == "UNAVAILABLE"
    assert response.json()["detail"] == "Database unavailable"
