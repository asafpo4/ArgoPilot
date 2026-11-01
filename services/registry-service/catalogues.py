import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from db import get_db

router = APIRouter(prefix="/v1")


@router.get("/crops")
def list_crops(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, str]]:
    rows = conn.execute("SELECT id, name FROM crops ORDER BY id").fetchall()
    return [dict(row) for row in rows]
