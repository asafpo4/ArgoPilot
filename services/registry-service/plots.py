import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from db import get_db

router = APIRouter(prefix="/v1")

# The plot columns, in the order the API returns them. Both routes select these, never SELECT *.
PLOT_COLUMNS = (
    "id, farm_id, name, area_m2, crop_id, planting_date, soil_id, "
    "row_spacing_m, emitter_spacing_m, emitter_id, lat, lon"
)


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
