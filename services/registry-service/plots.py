import sqlite3
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from db import get_db
from validation import (
    Latitude,
    Longitude,
    PlantingDate,
    PositiveNumber,
    RequiredName,
)

router = APIRouter(prefix="/v1")

# The plot columns, in the order the API returns them. Both routes select these, never SELECT *.
PLOT_COLUMNS = (
    "id, farm_id, name, area_m2, crop_id, planting_date, soil_id, "
    "row_spacing_m, emitter_spacing_m, emitter_id, lat, lon"
)

DUPLICATE_NAME_DETAIL = "Plot name already exists in this farm"


class PlotCreate(BaseModel):
    farm_id: str
    name: RequiredName
    area_m2: PositiveNumber
    crop_id: str
    planting_date: PlantingDate
    soil_id: str
    row_spacing_m: PositiveNumber
    emitter_spacing_m: PositiveNumber
    emitter_id: str
    lat: Latitude
    lon: Longitude


class PlotUpdate(BaseModel):
    farm_id: str | None = None
    name: RequiredName | None = None
    area_m2: PositiveNumber | None = None
    crop_id: str | None = None
    planting_date: PlantingDate | None = None
    soil_id: str | None = None
    row_spacing_m: PositiveNumber | None = None
    emitter_spacing_m: PositiveNumber | None = None
    emitter_id: str | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None

    @field_validator("*", mode="before")
    @classmethod
    def field_is_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("field must not be null")
        return value


def check_references(
    conn: sqlite3.Connection, farm_id: str, crop_id: str, soil_id: str, emitter_id: str
) -> None:
    # Checked in this order: farm first, then the three catalogue ids.
    checks = [
        ("SELECT 1 FROM farms WHERE id = ?", farm_id, 404, "Farm not found"),
        ("SELECT 1 FROM crops WHERE id = ?", crop_id, 422, "Unknown crop"),
        ("SELECT 1 FROM soils WHERE id = ?", soil_id, 422, "Unknown soil"),
        ("SELECT 1 FROM emitters WHERE id = ?", emitter_id, 422, "Unknown emitter"),
    ]
    for sql, value, status, detail in checks:
        if conn.execute(sql, (value,)).fetchone() is None:
            raise HTTPException(status_code=status, detail=detail)


@router.get("/plots")
def list_plots(
    conn: Annotated[sqlite3.Connection, Depends(get_db)], farm_id: str | None = None
) -> list[dict[str, str | float]]:
    if farm_id is None:
        rows = conn.execute(f"SELECT {PLOT_COLUMNS} FROM plots ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            f"SELECT {PLOT_COLUMNS} FROM plots WHERE farm_id = ? ORDER BY id", (farm_id,)
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/plots/{plot_id}")
def get_plot(plot_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str | float]:
    row = conn.execute(f"SELECT {PLOT_COLUMNS} FROM plots WHERE id = ?", (plot_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Plot not found")
    return dict(row)


@router.post("/plots", status_code=201)
def create_plot(body: PlotCreate, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> dict[str, str | float]:
    check_references(conn, body.farm_id, body.crop_id, body.soil_id, body.emitter_id)
    plot_id = str(uuid.uuid4())
    placeholders = ", ".join(["?"] * 12)
    try:
        conn.execute(
            f"INSERT INTO plots ({PLOT_COLUMNS}) VALUES ({placeholders})",
            (
                plot_id,
                body.farm_id,
                body.name,
                body.area_m2,
                body.crop_id,
                body.planting_date,
                body.soil_id,
                body.row_spacing_m,
                body.emitter_spacing_m,
                body.emitter_id,
                body.lat,
                body.lon,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # The write failed. Check the references again, in case one was removed after the first check.
        check_references(conn, body.farm_id, body.crop_id, body.soil_id, body.emitter_id)
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME_DETAIL) from None
    return {"id": plot_id, **body.model_dump()}


@router.patch("/plots/{plot_id}")
def update_plot(
    plot_id: str, body: PlotUpdate, conn: Annotated[sqlite3.Connection, Depends(get_db)]
) -> dict[str, str | float]:
    row = conn.execute(f"SELECT {PLOT_COLUMNS} FROM plots WHERE id = ?", (plot_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Plot not found")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return dict(row)
    merged = {**dict(row), **changes}
    check_references(conn, merged["farm_id"], merged["crop_id"], merged["soil_id"], merged["emitter_id"])
    try:
        cursor = conn.execute(
            "UPDATE plots SET farm_id = ?, name = ?, area_m2 = ?, crop_id = ?, planting_date = ?, "
            "soil_id = ?, row_spacing_m = ?, emitter_spacing_m = ?, emitter_id = ?, lat = ?, lon = ? "
            "WHERE id = ?",
            (
                merged["farm_id"],
                merged["name"],
                merged["area_m2"],
                merged["crop_id"],
                merged["planting_date"],
                merged["soil_id"],
                merged["row_spacing_m"],
                merged["emitter_spacing_m"],
                merged["emitter_id"],
                merged["lat"],
                merged["lon"],
                plot_id,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        check_references(conn, merged["farm_id"], merged["crop_id"], merged["soil_id"], merged["emitter_id"])
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME_DETAIL) from None
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Plot not found")
    return merged


@router.delete("/plots/{plot_id}", status_code=204)
def delete_plot(plot_id: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> Response:
    cursor = conn.execute("DELETE FROM plots WHERE id = ?", (plot_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Plot not found")
    return Response(status_code=204)
