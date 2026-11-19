"""Rounding and the plan JSON (spec 2.2 and 3.7).

Pure: no network, no clock, no environment. This is the only place where numbers are rounded;
the engine keeps full precision. Every rounded field is computed from its own full-precision value.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

from engine import EngineResult
from upstream import Forecast, PlotData

SOURCE = "open-meteo"
ASSUMED_START_RULE = "at_trigger"


def _round_decimal(value: float, digits: int) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("cannot round a non-finite number")
    # The shortest decimal text of the float, so 2.675 rounds as the text says (2.68).
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def round_half_up(value: float, digits: int) -> float:
    """Round to `digits` decimals, ties away from zero, working on the decimal text."""
    return float(_round_decimal(value, digits))


def _whole(value: float) -> int:
    return int(_round_decimal(value, 0))


def to_plan_json(
    plot_id: str,
    plot: PlotData,
    forecast: Forecast,
    result: EngineResult,
    days_requested: int,
) -> dict:
    """Build the 200 answer of spec 2.2 from the engine's full-precision result."""
    weather = {row.date: row for row in forecast.rows}
    days = []
    for day in result.days:
        row = weather[day.date]
        minutes = _whole(day.run_minutes)
        if day.irrigation_mm > 0:
            minutes = max(1, minutes)
        days.append(
            {
                "date": day.date.isoformat(),
                "stage": day.stage,
                "stale": forecast.stale,
                "et0_mm": row.et0_mm,
                "kc": round_half_up(day.kc, 3),
                "etc_mm": round_half_up(day.etc_mm, 2),
                "rain_mm": row.rain_mm,
                "rain_counted_mm": round_half_up(day.rain_counted_mm, 2),
                "irrigation_mm": round_half_up(day.irrigation_mm, 2),
                "litres": _whole(day.litres),
                "run_minutes": minutes,
                "capped": day.capped,
                "bucket_mm": round_half_up(day.bucket_mm, 2),
                "trigger_mm": round_half_up(day.trigger_mm, 2),
            }
        )

    warnings = [{"code": w.code, **w.numbers} for w in result.warnings]
    if len(forecast.rows) < days_requested:
        warnings.append(
            {
                "code": "forecast_short",
                "days_requested": days_requested,
                "days_received": len(forecast.rows),
            }
        )

    return {
        "plot_id": plot_id,
        "crop_id": plot.crop_id,
        "area_m2": plot.area_m2,
        "flow_lph": round_half_up(result.flow_lph, 2),
        "taw_mm": round_half_up(result.taw_mm, 2),
        "assumed_start": {
            "rule": ASSUMED_START_RULE,
            "bucket_mm": round_half_up(result.start_bucket_mm, 2),
        },
        "forecast": {"source": SOURCE, "fetched_at": forecast.fetched_at},
        "warnings": warnings,
        "days": days,
    }
