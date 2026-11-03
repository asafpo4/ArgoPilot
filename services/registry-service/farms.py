import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from db import get_db

router = APIRouter(prefix="/v1")


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
