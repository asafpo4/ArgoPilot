from datetime import date

import pytest

from engine import CROPS, day_number, stage_and_kc

# (crop, d, stage, kc): every row of the boundary table in spec 3.2.
BOUNDARIES = [
    ("tomato", -1, "initial", 0.6),
    ("tomato", 0, "initial", 0.6),
    ("tomato", 29, "initial", 0.6),
    ("tomato", 30, "development", 0.6),
    ("tomato", 31, "development", 0.61375),
    ("tomato", 69, "development", 1.13625),
    ("tomato", 70, "mid", 1.15),
    ("tomato", 114, "mid", 1.15),
    ("tomato", 115, "late", 1.15),
    ("tomato", 116, "late", 1.15 - 0.35 / 30),
    ("tomato", 144, "late", 1.15 - 0.35 * 29 / 30),
    ("tomato", 145, "late", 0.80),
    ("tomato", 146, "after_cycle", 0.80),
    ("bell-pepper", 29, "initial", 0.6),
    ("bell-pepper", 30, "development", 0.6),
    ("bell-pepper", 64, "development", 0.6 + 0.45 * 34 / 35),
    ("bell-pepper", 65, "mid", 1.05),
    ("bell-pepper", 104, "mid", 1.05),
    ("bell-pepper", 105, "late", 1.05),
    ("bell-pepper", 106, "late", 1.0425),
    ("bell-pepper", 124, "late", 0.9075),
    ("bell-pepper", 125, "late", 0.90),
    ("bell-pepper", 126, "after_cycle", 0.90),
]


@pytest.mark.parametrize(("crop_id", "d", "stage", "kc"), BOUNDARIES)
def test_stage_and_kc_boundaries(crop_id, d, stage, kc):
    got_stage, got_kc = stage_and_kc(CROPS[crop_id], d)
    assert got_stage == stage
    assert got_kc == pytest.approx(kc, rel=1e-9)


def test_boundary_values_match_the_spec_numbers():
    # The spec prints these to 6 decimals; the formulas above must agree.
    assert stage_and_kc(CROPS["tomato"], 116)[1] == pytest.approx(1.138333, abs=1e-6)
    assert stage_and_kc(CROPS["tomato"], 144)[1] == pytest.approx(0.811667, abs=1e-6)
    assert stage_and_kc(CROPS["bell-pepper"], 64)[1] == pytest.approx(1.037143, abs=1e-6)


def test_day_number_planting_day_is_zero():
    assert day_number(date(2026, 3, 1), date(2026, 3, 1)) == 0
    assert day_number(date(2026, 3, 1), date(2026, 11, 17)) == 261
    assert day_number(date(2026, 3, 1), date(2026, 2, 28)) == -1


def test_cycle_lengths():
    assert CROPS["tomato"].cycle_length == 145
    assert CROPS["bell-pepper"].cycle_length == 125
    assert CROPS["tomato"].cumulative_ends == (30, 70, 115, 145)
    assert CROPS["bell-pepper"].cumulative_ends == (30, 65, 105, 125)
