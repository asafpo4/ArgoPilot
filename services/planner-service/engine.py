"""The irrigation engine: a pure FAO-56 soil-water bucket.

Plain numbers and dates in, plain numbers out. No network, no clock, no environment, no
settings and no rounding. The rules are in docs/superpowers/specs/2026-11-17-planner-service-design.md
(Part 3) and the decisions in docs/judgment-log.md.
"""

from dataclasses import dataclass
from datetime import date
from itertools import accumulate


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
