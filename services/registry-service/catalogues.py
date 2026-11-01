import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from db import get_db

router = APIRouter(prefix="/v1")


@router.get("/crops")
def list_crops(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, str]]:
    rows = conn.execute("SELECT id, name FROM crops ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.get("/crops/{crop_id}")
def get_crop(crop_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str]:
    row = conn.execute("SELECT id, name FROM crops WHERE id = ?", (crop_id,)).fetchone()
    if row is None:
        # Temporary: replaced by the problem+json error format in the errors step.
        raise HTTPException(status_code=404, detail="Crop not found")
    return dict(row)
