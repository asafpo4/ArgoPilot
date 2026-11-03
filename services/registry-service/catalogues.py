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
        raise HTTPException(status_code=404, detail="Crop not found")
    return dict(row)


@router.get("/soils")
def list_soils(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, str | int]]:
    rows = conn.execute(
        "SELECT id, name, available_water_mm_per_m FROM soils ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/soils/{soil_id}")
def get_soil(soil_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str | int]:
    row = conn.execute(
        "SELECT id, name, available_water_mm_per_m FROM soils WHERE id = ?", (soil_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Soil not found")
    return dict(row)


@router.get("/emitters")
def list_emitters(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, str | float]]:
    rows = conn.execute("SELECT id, name, flow_lph FROM emitters ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.get("/emitters/{emitter_id}")
def get_emitter(emitter_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str | float]:
    row = conn.execute(
        "SELECT id, name, flow_lph FROM emitters WHERE id = ?", (emitter_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Emitter not found")
    return dict(row)
