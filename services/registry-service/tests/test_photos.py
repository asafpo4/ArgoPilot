"""Plot photos. S3 is replaced by FakeS3, so no test talks to AWS or needs credentials."""

from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi.testclient import TestClient

import photos

NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"
DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
UNKNOWN_PLOT = "00000000-0000-0000-0000-000000000000"
NORTH_KEY = f"{DEMO_COOPERATIVE}/{NORTH_BLOCK}/photo"
BUCKET = "test-agropilot-photos"

JPEG = b"\xff\xd8\xff\xe0 fake jpeg bytes"
PNG = b"\x89PNG fake png bytes"

ACCESS_DENIED = ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject")


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3:
    """Stands in for boto3.client("s3"). Set `error` to make every call raise it."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.regions: list[str | None] = []
        self.error: Exception | None = None

    def client(self, service: str, region_name: str | None = None) -> "FakeS3":
        assert service == "s3"
        self.regions.append(region_name)
        return self

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.calls.append(("put", Bucket, Key))
        if self.error:
            raise self.error
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append(("get", Bucket, Key))
        if self.error:
            raise self.error
        data, content_type = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data), "ContentType": content_type}


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    # Set before the `client` fixture starts the app, so startup reads these two settings.
    monkeypatch.setenv("AWS_S3_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    fake = FakeS3()
    monkeypatch.setattr(boto3, "client", fake.client)
    return fake


def upload(client: TestClient, plot_id: str, data: bytes, content_type: str) -> Any:
    return client.post(f"/v1/plots/{plot_id}/photo", files={"file": ("north.jpg", data, content_type)})


def test_upload_returns_201_with_key_and_stores_the_bytes_in_s3(s3: FakeS3, client: TestClient) -> None:
    response = upload(client, NORTH_BLOCK, JPEG, "image/jpeg")

    assert response.status_code == 201
    assert response.json() == {"plot_id": NORTH_BLOCK, "key": NORTH_KEY, "content_type": "image/jpeg"}
    assert s3.objects[(BUCKET, NORTH_KEY)] == (JPEG, "image/jpeg")
    assert s3.regions == ["us-east-1"]


def test_download_returns_the_uploaded_bytes_with_their_content_type(s3: FakeS3, client: TestClient) -> None:
    upload(client, NORTH_BLOCK, PNG, "image/png")

    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_second_upload_overwrites_the_first(s3: FakeS3, client: TestClient) -> None:
    upload(client, NORTH_BLOCK, JPEG, "image/jpeg")

    response = upload(client, NORTH_BLOCK, PNG, "image/png")

    assert response.status_code == 201
    assert response.json()["key"] == NORTH_KEY
    assert client.get(f"/v1/plots/{NORTH_BLOCK}/photo").content == PNG
    assert list(s3.objects) == [(BUCKET, NORTH_KEY)]


def test_upload_does_not_add_photo_fields_to_the_plot_json(s3: FakeS3, client: TestClient) -> None:
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()

    upload(client, NORTH_BLOCK, JPEG, "image/jpeg")

    assert client.get(f"/v1/plots/{NORTH_BLOCK}").json() == before


@pytest.mark.parametrize("plot_id", [UNKNOWN_PLOT, "bad%00id"])
def test_upload_to_unknown_plot_returns_404_without_calling_s3(
    s3: FakeS3, client: TestClient, plot_id: str
) -> None:
    response = upload(client, plot_id, JPEG, "image/jpeg")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert s3.calls == []


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"", "image/jpeg"),
        (JPEG, "image/gif"),
        (JPEG, "text/plain"),
        (b"x" * (photos.MAX_PHOTO_BYTES + 1), "image/jpeg"),
    ],
    ids=["empty", "gif", "text", "over-5-mb"],
)
def test_invalid_file_returns_422_without_calling_s3(
    s3: FakeS3, client: TestClient, data: bytes, content_type: str
) -> None:
    response = upload(client, NORTH_BLOCK, data, content_type)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION"
    assert s3.calls == []


def test_file_of_exactly_5_mb_is_accepted(s3: FakeS3, client: TestClient) -> None:
    response = upload(client, NORTH_BLOCK, b"x" * photos.MAX_PHOTO_BYTES, "image/webp")

    assert response.status_code == 201


def test_missing_file_field_returns_422(s3: FakeS3, client: TestClient) -> None:
    response = client.post(f"/v1/plots/{NORTH_BLOCK}/photo", data={"other": "value"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


@pytest.mark.parametrize("error", [ACCESS_DENIED, NoCredentialsError()], ids=["client-error", "no-credentials"])
def test_s3_error_on_upload_returns_503_and_keeps_the_stored_photo(
    s3: FakeS3, client: TestClient, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    upload(client, NORTH_BLOCK, PNG, "image/png")
    s3.error = error

    response = upload(client, NORTH_BLOCK, JPEG, "image/jpeg")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "UNAVAILABLE"
    assert type(error).__name__ in caplog.text
    s3.error = None
    stored = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")
    assert stored.content == PNG
    assert stored.headers["content-type"] == "image/png"


def test_s3_error_on_download_returns_503(s3: FakeS3, client: TestClient) -> None:
    upload(client, NORTH_BLOCK, JPEG, "image/jpeg")
    s3.error = NoCredentialsError()

    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")

    assert response.status_code == 503
    assert response.json()["code"] == "UNAVAILABLE"


@pytest.mark.parametrize("plot_id", [UNKNOWN_PLOT, "bad%00id"])
def test_download_for_unknown_plot_returns_404(s3: FakeS3, client: TestClient, plot_id: str) -> None:
    response = client.get(f"/v1/plots/{plot_id}/photo")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert s3.calls == []


def test_download_for_plot_without_photo_returns_404(s3: FakeS3, client: TestClient) -> None:
    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"
    assert s3.calls == []


def test_deleting_a_plot_with_a_photo_still_works(s3: FakeS3, client: TestClient) -> None:
    upload(client, NORTH_BLOCK, JPEG, "image/jpeg")

    assert client.delete(f"/v1/plots/{NORTH_BLOCK}").status_code == 204
    assert client.get(f"/v1/plots/{NORTH_BLOCK}/photo").status_code == 404
