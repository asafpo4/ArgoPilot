import pytest
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


def test_unexpected_error_returns_500_problem_json_without_internal_message(
    broken_client: TestClient,
) -> None:
    response = broken_client.get("/v1/farms")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "UNAVAILABLE"
    assert response.json()["detail"] == "Internal server error"
    assert "secret internal message" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "field"),
    [
        ("POST", "/v1/farms", "name"),
        ("PATCH", "/v1/farms/a9c1e4b2-6f70-4d8e-a144-3f8b5c904004", "name"),
        ("PATCH", "/v1/plots/c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002", "name"),
        ("PATCH", "/v1/plots/c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002", "crop_id"),
    ],
)
def test_lone_surrogate_text_returns_422_problem_json(
    client: TestClient, method: str, path: str, field: str
) -> None:
    # The JSON text holds the six characters \ud800, which is a lone surrogate.
    raw = '{"' + field + '": "\\ud800"}'

    response = client.request(method, path, content=raw, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"
    assert response.json()["detail"] == "Text contains invalid characters"


def test_validation_failure_title_is_unprocessable_entity(client: TestClient) -> None:
    response = client.post("/v1/farms", json={"name": ""})

    assert response.status_code == 422
    assert response.json()["title"] == "Unprocessable Entity"


def test_not_found_title_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/crops/potato")

    assert response.status_code == 404
    assert response.json()["title"] == "Not Found"
