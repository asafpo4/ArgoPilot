import sqlite3
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AfterValidator, BaseModel, field_validator

from db import get_db

router = APIRouter(prefix="/v1")


def strip_and_require_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be empty")
    return stripped


# The farm name rule, shared by the create and update models.
FarmName = Annotated[str, AfterValidator(strip_and_require_name)]


class FarmCreate(BaseModel):
    name: FarmName


class FarmUpdate(BaseModel):
    name: FarmName | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_is_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("name must not be null")
        return value


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


@router.patch("/farms/{farm_id}")
def update_farm(
    farm_id: str, body: FarmUpdate, conn: Annotated[sqlite3.Connection, Depends(get_db)]
) -> dict[str, str]:
    if conn.execute("SELECT 1 FROM farms WHERE id = ?", (farm_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        conn.execute("UPDATE farms SET name = ? WHERE id = ?", (changes["name"], farm_id))
        conn.commit()
    row = conn.execute("SELECT id, name FROM farms WHERE id = ?", (farm_id,)).fetchone()
    return dict(row)


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> Response:
    if conn.execute("SELECT 1 FROM farms WHERE id = ?", (farm_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    if conn.execute("SELECT 1 FROM plots WHERE farm_id = ? LIMIT 1", (farm_id,)).fetchone() is not None:
        raise HTTPException(status_code=409, detail="Farm has plots")
    conn.execute("DELETE FROM farms WHERE id = ?", (farm_id,))
    conn.commit()
    return Response(status_code=204)
