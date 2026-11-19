---
name: irrigation-calc-reference
description: Reference for how every number of the planner-service irrigation plan is calculated (engine.py, FAO-56 single crop coefficient and soil-water bucket). Use this skill whenever a question or a change touches how a number of the plan is computed, even a small one: Kc, ETc, p, RAW, TAW, rain counted, irrigation mm, litres, run minutes, the bucket and trigger levels, the 1440-minute cap, the stage or day count, or a warning. Gives the formulas with units, every constant with its FAO-56 source or the judgment-log entry that made it our own decision, the day-count convention, the limitations, and three worked cases with every intermediate value.
---

# irrigation-calc-reference

This is how `engine.py` turns a plot, a soil, an emitter and weather rows into
a plan. The engine is pure: numbers and dates in, numbers out, no rounding.
Rounding happens later, only when the JSON is built (kc 3 decimals, mm and
`flow_lph` 2 decimals, litres and minutes whole numbers). No AI model computes
or adjusts any number. If a number cannot be reproduced by hand from the
formulas below, that is a bug.

Sources: spec `docs/superpowers/specs/2026-11-17-planner-service-design.md`
(Part 3 and 5.4), `docs/research/fao56.md`, `docs/judgment-log.md`.

## 1. Formulas, in the order of the daily step

Inputs per plot: `crop_id`, `planting_date`, `area_m2` (m2), `row_spacing_m`
(m), `emitter_spacing_m` (m), emitter `flow_lph` (L/h per emitter), soil
`available_water_mm_per_m` (mm/m). Inputs per day: `ET0` (mm/day) and `rain`
(mm).

Once per plan:

- `TAW = available_water_mm_per_m x Zr` (mm). Same for every day. FAO Eq. 82.
- `cell_area = row_spacing_m x emitter_spacing_m` (m2 per emitter).
- `flow_lph = area_m2 / cell_area x emitter flow_lph` (L/h, whole plot). The
  number of emitters is not rounded.
- `cap_mm = 24 x emitter flow_lph / cell_area` (mm). The depth that 1440
  minutes of running gives.

For each weather row, in date order:

1. `d = date - planting_date` (whole days), then the stage and `Kc` (section 3).
2. `ETc = Kc x ET0` (mm/day). FAO Eq. 58.
3. `p = clamp(p_table + 0.04 x (5 - ETc), 0.1, 0.8)` (no unit, a fraction of TAW).
4. `RAW = p x TAW` (mm). FAO Eq. 83. The trigger level is `TAW - RAW`.
5. Day 1 only: the assumed start `D = RAW`. `D` is the depletion, the mm of
   water missing from the bucket (0 means full).
6. `rain counted = 0` if `rain < 0.2 x ET0`, else `rain` (mm). Rain exactly at
   the threshold counts. If ET0 is 0, any rain counts.
7. `before = min(TAW, max(0, D + ETc - rain counted))` (mm). A negative value
   is rain the bucket could not hold: it is lost and not carried (Eq. 85, 86,
   88). The upper limit TAW is Eq. 86.
8. `need = max(0, before - RAW)` (mm). A `need` below 1e-9 mm counts as 0 (float
   noise, entry 16).
   `irrigation = min(need, cap_mm)` (mm). `capped` is true when `need > cap_mm`.
9. `litres = irrigation x area_m2` (L). 1 mm over 1 m2 is 1 L.
10. `run_minutes = litres / flow_lph x 60` (min). When capped it is exactly 1440.
11. End of day: `D = before - irrigation`. `bucket = TAW - D` and
    `trigger = TAW - RAW` (mm).

Consequences worth knowing:

- Only the overshoot above RAW is irrigated, so on an irrigated, uncapped day
  `bucket == trigger`.
- On a capped day `D` can stay above RAW. The bucket then ends below the
  trigger, and the remaining depletion carries to the next day.
- `Ks` (FAO Eq. 84) is not used. ETc is always `Kc x ET0`.
- The engine raises `ValueError` for a non-positive area, spacing, flow or soil
  value, a non-finite or negative ET0 or rain, an unknown crop, no rows,
  dates that are not consecutive, and a non-finite result (for example
  `area_m2 = 1e308`).

## 2. Constants and where each one comes from

Per crop (days are initial / development / mid / late):

- Tomato: stages 30 / 40 / 45 / 30, cumulative ends 30, 70, 115, 145. Kc ini
  0.6, Kc mid 1.15, Kc end 0.80. p 0.40. Zr 0.7 m.
- Bell pepper: stages 30 / 35 / 40 / 20, cumulative ends 30, 65, 105, 125. Kc ini
  0.6, Kc mid 1.05, Kc end 0.90. p 0.30. Zr 0.5 m.

Sources:

- **Stage lengths: FAO-56 Table 11 (Ch. 6).** Tomato is the Mediterranean row
  (30 / 40 / 45 / 30 = 145). Bell pepper is the Europe and Mediterranean row
  (printed "25/30 35 40 20 125"). Our decision: one fixed row per crop, and the
  pepper init length read as 30 because only 30 sums to 125 (judgment log
  entry 4).
- **Kc ini, Kc mid, Kc end: FAO-56 Table 12 (Ch. 6).** Kc mid is 1.15 for
  tomato and 1.05 for pepper. Kc ini 0.6 is the Solanaceae group value (no
  per-crop value is printed). Kc end for pepper is 0.90. Our decision: tomato
  Kc end 0.80, the midpoint of the printed range 0.70-0.90 and also the group
  row value (entry 4). The staked-crop footnote (Kc mid about 1.15 pepper, 1.20
  tomato) is not applied (entry 4).
- **Kc between stages: FAO-56 Eq. 66 (Ch. 6).** Linear interpolation (section 3).
- **ETc = Kc x ET0: FAO-56 Eq. 58 (Ch. 6).**
- **p table value and Zr: FAO-56 Table 22 (Ch. 8).** Tomato p 0.40, pepper p
  0.30. The value of p applies at ETc about 5 mm/day.
  - Our decision: p is adjusted every day, `p = p(Table 22) + 0.04 (5 - ETc)`
    limited to 0.1-0.8. This is FAO's own adjustment (Table 22 footnote 2).
    The task's fixed "half" is not used (entry 1).
  - Our decision: Zr is fixed at the minimum of the Table 22 range (tomato
    0.7-1.5 m, pepper 0.5-1.0 m), as FAO suggests for scheduling (entry 6).
- **TAW: FAO-56 Eq. 82 (Ch. 8)**, with the registry value equal to
  (thetaFC - thetaWP) x 1000 (entry 6). **RAW: Eq. 83.**
- **Rain threshold 0.2 x ET0: FAO-56 Ch. 8**, the small-rain rule ("less than
  about 0.2 ETo ... can usually be ignored", single Kc approach). It is a rule
  of thumb, not an equation. Runoff is 0 and all other rain counts in full
  (entry 3).
- **Depletion step, limits and deep percolation: FAO-56 Eq. 85, 86, 88 (Ch. 8).**
- **Our own decisions, not FAO's:**
  - Day 1 starts at the trigger, `D = RAW` (entry 2).
  - Irrigate only the overshoot above RAW, never refill to field capacity
    (entry 2).
  - The cap of 1440 minutes a day, with depletion carried (entry 2).
  - Kc held at Kc end after the cycle, with a warning (entry 5).
  - Day 0 convention and no Ks (entry 11).
  - Very small irrigations are kept, no minimum dose (entry 10).
  - `bucket_mm = TAW - D` and `trigger_mm = TAW - RAW` as the reported levels
    (entry 7).

## 3. Day count, stages and Kc

**The planting date is day 0.** `d = date - planting_date` in whole days. This
is FAO's day number `i` in Eq. 66. The cycle covers `d = 0` to `d = L`, so it
spans `L + 1` calendar days, one more than FAO prints (entry 11).

With `C1`, `C2`, `C3` the cumulative stage ends and `L` the cycle length
(tomato 30, 70, 115, 145; bell pepper 30, 65, 105, 125), `L2` the length of
the development stage and `L4` the length of the late stage:

- `d < C1`: stage `initial`, Kc = Kc ini. This includes `d < 0` (planting date
  in the future).
- `C1 <= d < C2`: stage `development`, Kc = Kc ini + `(d - C1) / L2` x
  (Kc mid - Kc ini).
- `C2 <= d < C3`: stage `mid`, Kc = Kc mid.
- `C3 <= d <= L`: stage `late`, Kc = Kc mid + `(d - C3) / L4` x
  (Kc end - Kc mid).
- `d > L`: stage `after_cycle`, Kc = Kc end (held).

A boundary day belongs to the later stage, except `L`, which is the last
`late` day because the interpolation reaches Kc end there. The curve is
continuous at every boundary.

Warnings look at the first plan day `d1` only: `d1 > L` gives
`planting_date_past_cycle` with `days_past_cycle = d1 - L`; `d1 < 0` gives
`planting_date_in_future` with `days_until_planting = -d1`. A plan that crosses
a boundary later has no warning, and every day still carries its own stage.

## 4. Limitations (spec 3.9)

- No adjustment of Kc for wind or humidity (FAO Eq. 62 and 65 need wind and
  minimum humidity; weather gives only ET0 and rain). Table values stand for a
  standard climate.
- Kc ini is the table value for typical wetting. No adjustment for frequent
  wetting or for the wetted fraction of drip (Eq. 60).
- One row of Table 11 per crop, whatever the planting season. Fixed root depth
  at the Table 22 minimum.
- A young plant has shallower roots than the fixed depth, so in the first weeks
  the bucket is overestimated. In dry weather the daily dose is unchanged, but
  after heavy rain early in the season the plan can skip irrigation too long
  (entry 6).
- Rain is a forecast. Runoff is 0. The 0.2 x ET0 threshold is a rule of thumb,
  so the result jumps at it.
- The start level is an assumption (`assumed_start`). No margin for forecast
  error and no memory of missed irrigations.
- `Ks` is not used. After a capped day the crop can be below the no-stress
  limit, and the plan shows it (`bucket_mm` below `trigger_mm`).
- Very small irrigations are kept (entry 10).
- After the end of the cycle Kc is held at Kc end, with a warning (entry 5).

## 5. Three worked cases

Each case is a test in `tests/test_engine_cases.py`. Values are in full
precision, compared with a tolerance of 1e-6.

### Case A: the task's example

Tomato, planted 2026-03-01, loam 175 mm/m, 1000 m2, rows 1.5 m, emitters every
0.4 m at 1.0 L/h. One day: 2026-06-09, ET0 6.0 mm, rain 0.0 mm.

- `d` = 100. Stage `mid`.
- Kc = 1.15.
- ETc = 1.15 x 6.0 = 6.9 mm.
- TAW = 175 x 0.7 = 122.5 mm.
- p = 0.40 + 0.04 x (5 - 6.9) = 0.324.
- RAW = 0.324 x 122.5 = 39.69 mm. Start `D` = 39.69 mm.
- Rain counted = 0 mm (rain 0.0).
- Irrigation = 6.9 mm (the overshoot above RAW, below the cap).
- Litres = 6.9 x 1000 = 6900 L.
- Flow = 1000 / (1.5 x 0.4) x 1.0 = 1000 / 0.6 = 1666.67 L/h.
- Minutes = 6900 / 1666.67 x 60 = 248.4 min.
- Bucket = 122.5 - 39.69 = 82.81 mm. Trigger = 82.81 mm.

### Case B: rain, skipped days and a small irrigation

Same plot as case A. Five days from 2026-08-10, ET0 6.25 mm every day, rain
`[0.0, 19.7, 0.5, 0.0, 0.0]` mm.

Every day: `d` = 162, 163, 164, 165, 166. Stage `after_cycle`. Kc = 0.8.
ETc = 0.8 x 6.25 = 5.0 mm. p = 0.40 + 0.04 x (5 - 5.0) = 0.40. TAW = 122.5 mm.
RAW = 0.40 x 122.5 = 49.0 mm. Trigger = 122.5 - 49.0 = 73.5 mm. Start `D` = 49.0
mm. The rain threshold is 0.2 x 6.25. The flow is 1666.67 L/h, as in case A.

- Day 1 (08-10): rain counted 0.0. Irrigation 5.0 mm, 5000 L, 180.0 min.
  Bucket 73.5 mm (on the trigger).
- Day 2 (08-11): rain 19.7 counts, so rain counted 19.7. Irrigation 0, 0 L,
  0 min. Bucket 88.2 mm.
- Day 3 (08-12): rain 0.5 is below the threshold, so rain counted 0.0.
  Irrigation 0, 0 L, 0 min. Bucket 83.2 mm.
- Day 4 (08-13): rain counted 0.0. Irrigation 0, 0 L, 0 min. Bucket 78.2 mm.
- Day 5 (08-14): rain counted 0.0. Irrigation 0.3 mm, 300 L, 10.8 min. Bucket
  73.5 mm (on the trigger again).

### Case C: a bell pepper in the development stage

East block: bell pepper, planted 2026-04-12, clay loam 200 mm/m, 800 m2, rows
1.5 m, emitters every 0.4 m at 1.6 L/h. Two days from 2026-06-01, ET0 5.6 mm,
rain 0.0 mm.

Once: TAW = 200 x 0.5 = 100.0 mm. Flow = 800 / 0.6 x 1.6 = 2133.33 L/h.
Both days: stage `development`, rain counted 0.0 mm.

- Day 1 (2026-06-01): `d` = 50. Kc = 0.6 + (50 - 30) / 35 x (1.05 - 0.6) = 6/7 =
  0.857143. ETc = 4.8 mm. p = 0.30 + 0.04 x (5 - 4.8) = 0.308. RAW = 30.8 mm.
  Start `D` = 30.8 mm. Irrigation 4.8 mm. Litres 4.8 x 800 = 3840 L. Minutes =
  3840 / 2133.33 x 60 = 108.0 min. Bucket 69.2 mm. Trigger 69.2 mm.
- Day 2 (2026-06-02): `d` = 51. Kc = 0.6 + (51 - 30) / 35 x 0.45 = 0.87. ETc =
  0.87 x 5.6 = 4.872 mm. p = 0.30 + 0.04 x (5 - 4.872) = 0.30512. RAW = 30.512
  mm. Irrigation 5.16 mm. Litres 5.16 x 800 = 4128 L. Minutes = 4128 / 2133.33 x
  60 = 116.1 min. Bucket 69.488 mm. Trigger 69.488 mm.

On day 2 the plan irrigates 5.16 mm, more than ETc (4.872 mm), because RAW fell
by 0.288 mm and the depletion is brought back to the new RAW.
