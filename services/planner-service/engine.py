"""The irrigation engine: a pure FAO-56 soil-water bucket.

Plain numbers and dates in, plain numbers out. No network, no clock, no environment, no
settings and no rounding. The rules are in docs/superpowers/specs/2026-11-17-planner-service-design.md
(Part 3) and the decisions in docs/judgment-log.md.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import accumulate

RAIN_THRESHOLD_FACTOR = 0.2  # rain below this share of ET0 counts as 0 (entry 3)
P_SLOPE = 0.04  # change of p per mm/day of ETc (entry 1)
P_MIN = 0.1
P_MAX = 0.8
MAX_RUN_MINUTES = 1440.0  # the daily cap (entry 2)


@dataclass(frozen=True)
class CropParams:
    """Constants of one crop (FAO-56 Tables 11, 12 and 22, judgment log entries 1, 4 and 6)."""

    stage_days: tuple[int, int, int, int]  # initial, development, mid, late
    kc: tuple[float, float, float]  # Kc initial, mid, end
    p_table: float  # depletion fraction at ETc of about 5 mm/day
    root_depth_m: float

    @property
    def cumulative_ends(self) -> tuple[int, int, int, int]:
        c1, c2, c3, c4 = accumulate(self.stage_days)
        return (c1, c2, c3, c4)

    @property
    def cycle_length(self) -> int:
        return sum(self.stage_days)


CROPS: dict[str, CropParams] = {
    "tomato": CropParams((30, 40, 45, 30), (0.6, 1.15, 0.80), 0.40, 0.7),
    "bell-pepper": CropParams((30, 35, 40, 20), (0.6, 1.05, 0.90), 0.30, 0.5),
}


def day_number(planting: date, day: date) -> int:
    """Days since planting, with the planting date as day 0 (spec 3.2)."""
    return (day - planting).days


def stage_and_kc(crop: CropParams, d: int) -> tuple[str, float]:
    """The growth stage and the crop coefficient on day `d` (spec 3.2, FAO-56 Eq. 66).

    A boundary day belongs to the later stage, except the last cycle day `L`, which is still
    `late` because the interpolation reaches Kc end there.
    """
    kc_ini, kc_mid, kc_end = crop.kc
    _, dev_days, _, late_days = crop.stage_days
    c1, c2, c3, last = crop.cumulative_ends
    if d < c1:
        return "initial", kc_ini
    if d < c2:
        return "development", kc_ini + (d - c1) / dev_days * (kc_mid - kc_ini)
    if d < c3:
        return "mid", kc_mid
    if d <= last:
        return "late", kc_mid + (d - c3) / late_days * (kc_end - kc_mid)
    return "after_cycle", kc_end


@dataclass(frozen=True)
class PlotInput:
    crop_id: str
    planting_date: date
    area_m2: float
    row_spacing_m: float
    emitter_spacing_m: float
    emitter_flow_lph: float
    soil_mm_per_m: float


@dataclass(frozen=True)
class WeatherRow:
    date: date
    et0_mm: float
    rain_mm: float


@dataclass(frozen=True)
class PlanWarning:
    code: str
    numbers: dict[str, int]


@dataclass(frozen=True)
class DayResult:
    date: date
    d: int
    stage: str
    kc: float
    etc_mm: float
    p: float
    raw_mm: float
    rain_counted_mm: float
    irrigation_mm: float
    capped: bool
    litres: float
    run_minutes: float
    depletion_mm: float
    bucket_mm: float
    trigger_mm: float


@dataclass(frozen=True)
class EngineResult:
    taw_mm: float
    flow_lph: float
    start_bucket_mm: float
    days: tuple[DayResult, ...]
    warnings: tuple[PlanWarning, ...]


def _check_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def _validate(plot: PlotInput, rows: Sequence[WeatherRow]) -> CropParams:
    crop = CROPS.get(plot.crop_id)
    if crop is None:
        raise ValueError("unknown crop")
    _check_positive(plot.area_m2, "area_m2")
    _check_positive(plot.row_spacing_m, "row_spacing_m")
    _check_positive(plot.emitter_spacing_m, "emitter_spacing_m")
    _check_positive(plot.emitter_flow_lph, "emitter_flow_lph")
    _check_positive(plot.soil_mm_per_m, "soil_mm_per_m")
    if not rows:
        raise ValueError("no weather rows")
    for row in rows:
        for value, name in ((row.et0_mm, "et0_mm"), (row.rain_mm, "rain_mm")):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite number, not negative")
    for previous, row in zip(rows, rows[1:]):
        if row.date != previous.date + timedelta(days=1):
            raise ValueError("weather dates must be consecutive")
    return crop


def plan(plot: PlotInput, rows: Sequence[WeatherRow]) -> EngineResult:
    """Run the soil-water bucket over the weather rows (spec 3.3 to 3.6). No rounding."""
    crop = _validate(plot, rows)
    taw = plot.soil_mm_per_m * crop.root_depth_m
    cell_area = plot.row_spacing_m * plot.emitter_spacing_m
    flow_lph = plot.area_m2 / cell_area * plot.emitter_flow_lph
    cap_mm = 24 * plot.emitter_flow_lph / cell_area

    days: list[DayResult] = []
    depletion = 0.0
    start_bucket = 0.0
    for index, row in enumerate(rows):
        d = day_number(plot.planting_date, row.date)
        stage, kc = stage_and_kc(crop, d)
        etc = kc * row.et0_mm
        p = min(P_MAX, max(P_MIN, crop.p_table + P_SLOPE * (5 - etc)))
        raw = p * taw
        if index == 0:
            depletion = raw  # the assumed start (entry 2)
            start_bucket = taw - depletion
        counted = 0.0 if row.rain_mm < RAIN_THRESHOLD_FACTOR * row.et0_mm else row.rain_mm
        before = min(taw, max(0.0, depletion + etc - counted))
        need = max(0.0, before - raw)
        capped = need > cap_mm
        irrigation = cap_mm if capped else need
        litres = irrigation * plot.area_m2
        run_minutes = MAX_RUN_MINUTES if capped else litres / flow_lph * 60
        depletion = before - irrigation
        days.append(
            DayResult(
                date=row.date,
                d=d,
                stage=stage,
                kc=kc,
                etc_mm=etc,
                p=p,
                raw_mm=raw,
                rain_counted_mm=counted,
                irrigation_mm=irrigation,
                capped=capped,
                litres=litres,
                run_minutes=run_minutes,
                depletion_mm=depletion,
                bucket_mm=taw - depletion,
                trigger_mm=taw - raw,
            )
        )

    for value in (taw, flow_lph, start_bucket):
        if not math.isfinite(value):
            raise ValueError("result is not finite")
    for day in days:
        if not (math.isfinite(day.litres) and math.isfinite(day.run_minutes)):
            raise ValueError("result is not finite")

    warnings: list[PlanWarning] = []
    first_d = days[0].d
    if first_d > crop.cycle_length:
        warnings.append(
            PlanWarning("planting_date_past_cycle", {"days_past_cycle": first_d - crop.cycle_length})
        )
    elif first_d < 0:
        warnings.append(PlanWarning("planting_date_in_future", {"days_until_planting": -first_d}))
    return EngineResult(taw, flow_lph, start_bucket, tuple(days), tuple(warnings))
