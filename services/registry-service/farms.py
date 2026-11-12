import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

import db
from db import IntegrityViolation, get_db
from validation import RequiredName, contains_nul

router = APIRouter(prefix="/v1")


class FarmCreate(BaseModel):
    name: RequiredName


class FarmUpdate(BaseModel):
    name: RequiredName | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_is_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("name must not be null")
        return value


@router.get("/farms")
def list_farms(conn: Annotated[db.Connection, Depends(get_db)]) -> list[dict[str, str]]:
    rows = conn.execute("SELECT id, name FROM farms ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.get("/farms/{farm_id}")
def get_farm(farm_id: str, conn: Annotated[db.Connection, Depends(get_db)]) -> dict[str, str]:
    if contains_nul(farm_id):
        raise HTTPException(status_code=404, detail="Farm not found")
    row = conn.execute("SELECT id, name FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return dict(row)


@router.post("/farms", status_code=201)
def create_farm(body: FarmCreate, conn: Annotated[db.Connection, Depends(get_db)]) -> dict[str, str]:
    farm_id = str(uuid.uuid4())
    conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", (farm_id, body.name))
    conn.commit()
    return {"id": farm_id, "name": body.name}


@router.patch("/farms/{farm_id}")
def update_farm(
    farm_id: str, body: FarmUpdate, conn: Annotated[db.Connection, Depends(get_db)]
) -> dict[str, str]:
    if contains_nul(farm_id):
        raise HTTPException(status_code=404, detail="Farm not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        conn.execute("UPDATE farms SET name = ? WHERE id = ?", (changes["name"], farm_id))
        conn.commit()
    row = conn.execute("SELECT id, name FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Farm not found")
    return dict(row)


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: str, conn: Annotated[db.Connection, Depends(get_db)]) -> Response:
    if contains_nul(farm_id):
        raise HTTPException(status_code=404, detail="Farm not found")
    try:
        cursor = conn.execute("DELETE FROM farms WHERE id = ?", (farm_id,))
        conn.commit()
    except IntegrityViolation:
        # A plot still refers to this farm, so the foreign key refuses the delete.
        raise HTTPException(status_code=409, detail="Farm has plots") from None
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Farm not found")
    return Response(status_code=204)
