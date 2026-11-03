import sqlite3
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from db import get_db

router = APIRouter(prefix="/v1")


class FarmCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def strip_and_require_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty")
        return stripped


@router.get("/farms")
def list_farms(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, str]]:
    rows = conn.execute("SELECT id, name FROM farms ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.get("/farms/{farm_id}")
def get_farm(farm_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str]:
    row = conn.execute("SELECT id, name FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return dict(row)


@router.post("/farms", status_code=201)
def create_farm(body: FarmCreate, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str]:
    farm_id = str(uuid.uuid4())
    conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", (farm_id, body.name))
    conn.commit()
    return {"id": farm_id, "name": body.name}
