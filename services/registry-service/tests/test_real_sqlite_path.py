import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db import DB_PATH, get_db
from main import app


def test_real_sqlite_path_reads_and_writes_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No get_db override: this goes through get_db -> connect_target -> connect.
    copy = tmp_path / "registry.db"
    shutil.copy(DB_PATH, copy)
    original = DB_PATH.read_bytes()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(copy))
    assert get_db not in app.dependency_overrides

    with TestClient(app) as test_client:
        assert get_db not in app.dependency_overrides
        crops = test_client.get("/v1/crops")
        assert crops.status_code == 200
        assert len(crops.json()) > 0

        created = test_client.post("/v1/farms", json={"name": "Real path farm"})
        assert created.status_code == 201
        farm_id = created.json()["id"]
        read_back = test_client.get(f"/v1/farms/{farm_id}")
        assert read_back.status_code == 200
        assert read_back.json()["name"] == "Real path farm"

    assert DB_PATH.read_bytes() == original


def test_real_sqlite_path_missing_file_returns_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "missing.db"))
    assert get_db not in app.dependency_overrides

    with TestClient(app) as test_client:
        response = test_client.get("/v1/crops")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "UNAVAILABLE"
    assert not (tmp_path / "missing.db").exists()
