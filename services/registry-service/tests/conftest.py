import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db import DB_PATH, get_db
from main import app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    test_db = tmp_path / "registry.db"
    shutil.copy(DB_PATH, test_db)

    def override_get_db() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"{test_db.as_uri()}?mode=rw", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
