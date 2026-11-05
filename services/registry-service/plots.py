import sqlite3
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_db
from validation import PlantingDate, PositiveNumber, RequiredName

router = APIRouter(prefix="/v1")

# The plot columns, in the order the API returns them. Both routes select these, never SELECT *.
PLOT_COLUMNS = (
    "id, farm_id, name, area_m2, crop_id, planting_date, soil_id, "
    "row_spacing_m, emitter_spacing_m, emitter_id, lat, lon"
)


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
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]


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
    plot_id = str(uuid.uuid4())
    placeholders = ", ".join(["?"] * 12)
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
    return {"id": plot_id, **body.model_dump()}
