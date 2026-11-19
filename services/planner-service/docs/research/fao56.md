# FAO-56 research notes: crop water need, Kc, soil water bucket, Annex 8

Scope: FAO Irrigation and Drainage Paper 56 (Allen et al., 1998), Ch. 5, 6, 8 and Annex 8, for a daily drip-irrigation planner (tomato, bell pepper). Explanation and FAO's printed formulas only; no code.

IMPORTANT numbering note: in FAO-56 the chapters are: Ch. 5 = introduction to ETc; Ch. 6 = ETc, single crop coefficient; Ch. 7 = ETc, dual crop coefficient (Kc = Kcb + Ke); Ch. 8 = ETc under soil water stress. The dual approach is therefore in Ch. 7 (not Ch. 6). Table 19 and Table 20 are on the Ch. 7 page. (Source: FAO index page.)

## Sources and access

All fetched through WebFetch (the index URL redirected 301 to the /4/ path). IMPORTANT limitation: WebFetch returns a model-produced digest of each page, not raw HTML. It refused verbatim long quotes, so every number below is as relayed by that digest and could not be compared against the raw page. Equation images were not delivered.

| URL | Readable? |
|---|---|
| http://www.fao.org/4/x0490E/x0490e00.htm (index, from https://www.fao.org/3/x0490E/x0490e00.htm) | Fully (links only) |
| http://www.fao.org/4/x0490E/x0490e0a.htm (Ch. 5) | Text readable; no formulas missing that matter |
| http://www.fao.org/4/x0490E/x0490e0b.htm (Ch. 6, Tables 11, 12) | Text and tables readable; Eq. 59, 62-66 are images (not readable); Kc ini per-crop column blank/image |
| http://www.fao.org/4/x0490E/x0490e0c.htm (Ch. 7, Tables 19, 20) | Readable (read only for Table 19/20 and definitions of Kcb, Ke) |
| http://www.fao.org/4/x0490E/x0490e0e.htm (Ch. 8, Table 22) | Mostly readable; Eq. 84, 89-93 and Figures are images |
| http://www.fao.org/4/x0490E/x0490e0p.htm (Annex 8) | Readable as a description; the daily numeric table is not in the text |

## Access gaps

- Equation images not readable: Ch. 6 Eq. 59, 62, 65, 66 (only their variables and purpose are known); Ch. 8 Eq. 84 (Ks formula) and Eq. 89-93 (salinity). I did not fill these from memory. A developer must read these formulas directly in FAO-56 (Ch. 8, Eq. 84 is the important one).
- Table 12: the per-crop Kc ini column came back blank for tomato and pepper; only the group row value is available (see 2).
- Digest-not-verbatim: all numbers are UNVERIFIED against raw page text in the strict sense (they come from a digest). They should be cross-checked against the page once before use in code.
- Annex 8: the daily rows (day 16 onward) with numbers are not available; only inputs, column structure and procedure. The digest also reported apparent inconsistencies in the annex (listed in 4); some of these may be digest errors. Equation numbers attached to Annex columns are UNVERIFIED.
- Ch. 5 does not discuss effective rainfall. Ch. 8 has no named "effective rainfall" quantity, but it gives one rule for small rain in the precipitation part of the bucket section (see 1).

## 1. From ET0 and Kc to crop water need (Ch. 5, Ch. 6, Ch. 7)

- ET0 is the evapotranspiration of a well-watered hypothetical grass reference surface with fixed height, albedo and surface resistance; "The reference ETo is defined and calculated using the FAO Penman-Monteith equation (Chapter 4)" (Ch. 5). Treat it as an input here.
- ETc is crop ET under standard conditions (large fields, excellent agronomic and soil water management, no stress) (Ch. 5, Ch. 6).
- Single crop coefficient: `ETc = Kc ETo` (Eq. 58, Ch. 6; also stated as Eq. 56 in Ch. 5). "The effect of both crop transpiration and soil evaporation are integrated into a single crop coefficient" (Ch. 6).
- Kc is the ratio ETc/ETo; it reflects crop height, albedo, canopy resistance and soil evaporation differences from grass, depends mainly on the crop and little on climate (Ch. 5).
- Dual approach (what it is): Kc is split into basal crop coefficient Kcb (transpiration, dry soil surface, plus small residual evaporation) and soil evaporation coefficient Ke (largest after rain/irrigation wetting, near zero when the surface is dry): `Kc = Kcb + Ke` (Eq. 57, Ch. 5); `ETc = (Kcb + Ke) ETo` (Eq. 69, Ch. 7).
- Non-standard conditions: ETc adj (water stress, salinity, pests) is dealt with in Part C (Ch. 5; Ch. 8-10). Ch. 8 gives ETc adj (section 3).
- Effective rainfall / net irrigation requirement: Ch. 5 does not discuss either (per the digest). The only place in these chapters tying crop need to irrigation is Ch. 8: precipitation P, runoff RO and net irrigation I enter the daily root zone balance (Eq. 85) and the "Forecasting or allocating irrigations" section: irrigate at or before Dr,i reaches RAW, and keep net irrigation depth Ii <= Dr,i to limit deep percolation.
- Small rain (Ch. 8, the precipitation, runoff and irrigation part of the bucket section, right after Eq. 85 defines P, RO and I; read on the raw page): "Daily precipitation in amounts less than about 0.2 ETo is normally entirely evaporated and can usually be ignored in the water balance calculations especially when the single crop coefficient approach is used". It is a rule of thumb ("about", "normally", "usually"), not an equation. Ch. 8 has no other effective-rainfall rule in the sections read.

## 2. Growth stages, Kc curve, tomato and bell pepper values

### 2.1 Stages and curve construction (Ch. 6)

- Four stages: initial, crop development, mid-season, late season. Table 11 gives typical lengths; FAO stresses local observations take precedence (Ch. 6, Length of growth stages).
- Only three Kc values describe the curve: Kc ini, Kc mid, Kc end (Table 12) (Ch. 6).
- Procedure (Ch. 6, Construction of the Kc curve): (1) divide the season into the four stages, get lengths, pick the three Kc values; (2) adjust Kc values for wetting frequency and climate; (3) draw the curve: horizontal lines through Kc ini (initial) and Kc mid (mid-season), straight diagonal lines in development (Kc ini to Kc mid) and late season (Kc mid to Kc end); (4) ETc = Kc ETo.
- Eq. 66 gives Kc on day i by linear interpolation in the development and late stages, using day number i, the stage length and the sum of lengths of previous stages (formula is an image: UNVERIFIED).
- Adjustments in Ch. 6: Eq. 59 interpolates Kc ini between light (Fig. 29) and heavy (Fig. 30) wetting events for infiltration depth 10-40 mm; Eq. 62 adjusts Kc mid and Eq. 65 adjusts Kc end for u2 (1-6 m/s), RHmin (20-80 %) and plant height h (0.1-10 m); Eq. 65 applies only when tabulated Kc end > 0.45. Higher wind / lower humidity raise Kc mid/end; the reverse lowers them. Formulas are images (not read).

### 2.2 Table 11: lengths of stages (days), Ch. 6

| Crop | Init | Dev | Mid | Late | Total | Planting date | Region |
|---|---|---|---|---|---|---|---|
| Sweet peppers (bell) | 25/30 | 35 | 40 | 20 | 125 | April/June | Europe and Medit. |
| Sweet peppers (bell) | 30 | 40 | 110 | 30 | 210 | October | Arid Region |
| Tomato | 30 | 40 | 40 | 25 | 135 | January | Arid Region |
| Tomato | 35 | 40 | 50 | 30 | 155 | Apr/May | Calif., USA |
| Tomato | 25 | 40 | 60 | 30 | 155 | Jan | Calif. Desert, USA |
| Tomato | 35 | 45 | 70 | 30 | 180 | Oct/Nov | Arid Region |
| Tomato | 30 | 40 | 45 | 30 | 145 | April/May | Mediterranean |

Footnote: stage lengths are "indicative of general conditions" and may vary substantially by region, climate, cropping conditions and variety. No footnote is specific to tomato or pepper. Note: the digest said the crop name was inferred by row position for the second pepper and the four later tomato rows (so those labels are slightly UNVERIFIED).

### 2.3 Table 12: Kc and max height, Ch. 6 (section "b. Vegetables - Solanum Family (Solanaceae)")

| Row | Kc ini | Kc mid | Kc end | Max height h (m) |
|---|---|---|---|---|
| Group row (Solanaceae) | 0.6 | 1.15 | 0.80 | not given |
| Egg plant (for context) | blank | 1.05 | 0.90 | 0.8 |
| Sweet peppers (bell) | blank (group value 0.6 applies) | 1.05 (footnote 2) | 0.90 | 0.7 |
| Tomato | blank (group value 0.6 applies) | 1.15 (footnote 2) | 0.70-0.90 | 0.6 |

- Kc ini: FAO states that for several groups only one Kc ini is listed and "is considered to be representative of the whole group" (Table 12 text). The column was blank per crop in the digest, so 0.6 is the group value. The group-row Kc mid 1.15 and Kc end 0.80 differ from the crop rows; use the crop rows.
- Table 12 has no separate "Pepper fresh market" entry; "Sweet peppers (bell)" is the only pepper row. Tomato has a single row (no variants); Kc end is given as a range 0.70-0.90.
- Footnote 1 (Kc ini): general values for typical irrigation and soil wetting; with frequent wetting (e.g. high-frequency sprinkler, daily rain) Kc ini can rise substantially, approaching 1.0-1.2; better estimated from Fig. 29-30, Eq. 7-3 (Annex 7) or the dual Kcb + Ke approach.
- Footnote 2 (stalked crops): peppers and tomatoes are sometimes grown on stakes 1.5-2 m tall; then higher Kc mid applies: peppers about 1.15, tomatoes about 1.20, and h should be increased.
- No footnote marker on pepper/tomato Kc end in the digest.
- Climate adjustment of Kc mid/end: use Eq. 62 and 65 with table values as standard climate (RHmin about 45 %, u2 about 2 m/s) (the standard-climate numbers are not in my digests: UNVERIFIED, only the ranges above are).
- Drip / partial wetting (Ch. 6): `Kc ini = fw Kc ini(Tab, Fig)` (Eq. 60) when only part of the surface is wetted; `Iw = I / fw` (Eq. 61) is the depth to use with Fig. 29/30. Example 26: trickle, fw = 0.4, 12 mm per event, Iw = 30 mm, interpolated Kc ini = 1.05, adjusted 0.42, ETc about 1.7 mm/day. Trickle can wet about 0.4 of the surface.
- Table 20 (Ch. 7, fw, fraction of surface wetted): precipitation 1.0; sprinkler 1.0; basin 1.0; border 1.0; furrow every furrow narrow bed 0.6-1.0; wide bed 0.4-0.6; alternate furrows 0.3-0.5; trickle 0.3-0.4.

## 3. Soil water bucket (Ch. 8)

Equations (numbers as printed; Eq. 84 is an image):

| Eq. | Content |
|---|---|
| 80 | `ETc adj = (Ks Kcb + Ke) ETo` (dual approach) |
| 81 | `ETc adj = Ks Kc ETo` (single approach) |
| 82 | `TAW = 1000 (thetaFC - thetaWP) Zr` (mm; theta in m3/m3, Zr in m) |
| 83 | `RAW = p TAW` |
| 84 | Ks for Dr > RAW: formula is an image (UNVERIFIED, not reproduced). Ks = 1 when Dr <= RAW; Ks is "a dimensionless transpiration reduction factor dependent on available soil water [0 - 1]". |
| 85 | `Dr,i = Dr,i-1 - (Pi - ROi) - Ii - CRi + ETc,i + DPi` |
| 86 | `0 <= Dr,i <= TAW` |
| 87 | `Dr,i-1 = 1000 (thetaFC - theta i-1) Zr` (initial depletion from measured water content) |
| 88 | `DPi = (Pi - ROi) + Ii - ETc,i - Dr,i-1 >= 0` (only after heavy rain/irrigation; Dr,i then 0) |

Definitions: TAW = total available water in the root zone (mm), field capacity minus wilting point times rooting depth. RAW = readily available water (mm). p = average fraction of TAW that can be depleted before stress (0-1). Dr = root zone depletion (mm), 0 at field capacity; stress begins when Dr > RAW. P precipitation, RO runoff, I net irrigation depth infiltrating, CR capillary rise, ETc crop ET, DP deep percolation (all mm, day i).

- p adjustment: `p = p(Table 22) + 0.04 (5 - ETc)`, ETc in mm/day, p limited to 0.1-0.8 (Ch. 8; Table 22 fn 2).
- Daily stepping: Dr,i from Dr,i-1 via Eq. 85, bounded by Eq. 86; Ch. 8 sub-sections: limits on Dr,i, initial depletion (Eq. 87), precipitation/runoff/irrigation, capillary rise, evapotranspiration, deep percolation (Eq. 88).
- Timing/depth (Ch. 8, Forecasting or allocating irrigations): irrigate at or before Dr,i >= RAW; Ii <= Dr,i.
- Example 37 (consistent with Eq. 84): Dr = 67 mm, TAW = 160 mm, p = 0.4 gives Ks about 0.97 (digest inference).

### Table 19 (Ch. 7 page): typical soil water characteristics, USA texture classes

| Soil | thetaFC | thetaWP | thetaFC - thetaWP (m3/m3) | REW stage 1 (mm) | TEW (mm), Ze = 0.10 m |
|---|---|---|---|---|---|
| Sand | 0.07-0.17 | 0.02-0.07 | 0.05-0.11 | 2-7 | 6-12 |
| Loamy sand | 0.11-0.19 | 0.03-0.10 | 0.06-0.12 | 4-8 | 9-14 |
| Sandy loam | 0.18-0.28 | 0.06-0.16 | 0.11-0.15 | 6-10 | 15-20 |
| Loam | 0.20-0.30 | 0.07-0.17 | 0.13-0.18 | 8-10 | 16-22 |
| Silt loam | 0.22-0.36 | 0.09-0.21 | 0.13-0.19 | 8-11 | 18-25 |
| Silt | 0.28-0.36 | 0.12-0.22 | 0.16-0.20 | 8-11 | 22-26 |
| Silt clay loam | 0.30-0.37 | 0.17-0.24 | 0.13-0.18 | 8-11 | 22-27 |
| Silty clay | 0.30-0.42 (printed "0-30": digest says typo; UNVERIFIED) | 0.17-0.29 | 0.13-0.19 | 8-12 | 22-28 |
| Clay | 0.32-0.40 | 0.20-0.24 | 0.12-0.20 | 8-12 | 22-29 |

Footnote: TEW = (thetaFC - 0.5 thetaWP) Ze, Ze in m. REW and TEW are for the evaporation layer (dual approach); Ch. 8 refers to Table 19 for FC/WP ranges.

### Table 22 (Ch. 8): maximum root depth and depletion fraction

| Crop | Max root depth Zr (m) | p (for ETc about 5 mm/day) |
|---|---|---|
| Egg plant | 0.7-1.2 | 0.45 |
| Sweet peppers (bell) | 0.5-1.0 | 0.30 |
| Tomato | 0.7-1.5 | 0.40 |

Footnotes: larger Zr for soils without restrictive layers; smaller Zr suit irrigation scheduling, larger suit modelling stress or rainfed use; p applies at ETc about 5 mm/day and is adjusted by the formula above. Table 22 has no separate "Pepper" row.

### Drip / partial wetting in Ch. 8
The digest found no discussion of partial wetting or fw in Ch. 8 (trickle appears only in the salinity section). fw is in Ch. 6 (Eq. 60-61) and Ch. 7 (Table 20, and fw/few for Ke). Ch. 8 also covers salinity (Eq. 89-93) and yield response, not read in detail.

## 4. Annex 8: daily scheduling example

What it is: a spreadsheet implementation of the dual Kc method plus daily root zone balance for dry edible beans, Kimberly, Idaho, 1974 (Boxes 15, 16 of Ch. 6-7). It is not tomato/pepper. Assumptions: irrigation and precipitation early morning, drainage the same day, runoff zero, each irrigation refills to the previous day's depletion; the schedule is theoretical (Fig. 8.1) vs. the actual 1974 schedule in Box 16.

Inputs: planting 22 May 1974; stage lengths Lini/Ldev/Lmid/Llate = 25/25/30/20 days; Kcb ini 0.15, Kcb mid 1.10 (before adjustment), Kcb end 0.25; max height 0.40 m; root depth min/max 0.20/0.80 m; available water 160 mm/m; MAD 70 % initially and 45 % after the initial period; irrigation wetted fraction fw 0.5; REW 8 mm; TEW 22 mm; initial De 18 mm; initial fw 1. Derived day-of-year: planting 142, development 167, mid 192, late 222, harvest 242. Simulation starts 15 May (day 135).

Columns (digest, cell letters): date/day of year; Tdew; u2; Tmin; ETo; saturation and actual vapour pressure and RHmin; precipitation; Kcb of the day (interpolated); crop height; Kc max (Eq. 72); irrigation depth / fw; evaporation-layer terms (fw, few, De start, Kr Eq. 71, Ke, evaporation Eq. 79, drainage Eq. 77, De end); Kc = Kcb + Ke (Eq. 69); ETc = Kc ETo; Zr (Eq. 8-1: Zr = Rootmin + (Kcb - Kcmin)/(Kcmid - Kcmin) x (Rootmax - Rootmin), never decreasing; Zr max after mid-season, Eq. 8-2); RAW = MAD x Zr x 160 mm/m (never decreasing); first-pass depletion; next-day irrigation (Eq. 88); drainage; Ks = (TAW - Dr)/(TAW - RAW) when Dr > RAW else 1, TAW = Zr x 160 (as read in the digest; compare with printed Eq. 84); adjusted Kc = Ke + Kcb Ks; end-of-day root zone depletion.

Daily order: (1) day number, vapour pressure, RHmin; (2) Kcb by stage (Kcb ini before development, linear rise to Kcb mid adjusted by Eq. 70, flat in mid, linear decline to Kcb end, back to ini after harvest); (3) height and Kc max; (4) Zr and RAW; (5) apply irrigation decided the previous day, set fw; (6) evaporation layer: De, Kr, few, Ke, evaporation, drainage, end De; (7) Kc and ETc; (8) first-pass depletion, Ks, adjusted Kc, end-of-day Dr; (9) decide tomorrow's irrigation.

Trigger and amount: decided at day end; irrigate next morning when end-of-day depletion exceeds RAW (first-pass depletion > RAW), only before the midpoint of late season to harvest ((Jlate + Jharv)/2). Applied net depth = end-of-day depletion (refills to field capacity); the gross wetted-area depth is net/fw (0.5). Day 1 irrigation is zero. Stress can occur on the day before irrigation (Ks < 1), with small effect on Kc adj.

Carry-over: De, Zr, RAW, height and Kc max cap carry from the previous day (with MAX); root zone depletion carries from the previous day's end value adjusted by P, irrigation, ETc and drainage; fw carries until the next rain or irrigation (rain sets 1, irrigation sets 0.5).

Digest-reported oddities (possible digest errors, UNVERIFIED): last irrigation date 225 in text vs 232 by formula; some row 15 formulas referencing row 14; RHmin formula appearing inverted; equation numbers for RAW/AK shown as Eq. 85 and Eq. 80 do not match Ch. 8's numbering (inference: annex numbers are loosely attributed).

## 5. Verification and gap fill (added after reading the raw FAO pages and the equation images)

Method: the raw HTML pages (http://www.fao.org/4/x0490E/x0490e0a.htm, e0b, e0e) and the equation GIFs were downloaded with curl, and each GIF was read as an image. This replaces the "digest, not verbatim" limitation for the items below.

Checked against the raw page text (all match sections 1 to 4 above):
- Chapter numbering: Ch. 5 intro to ETc, Ch. 6 single Kc, Ch. 7 dual Kc, Ch. 8 ETc under soil water stress.
- Table 12 (Ch. 6): group row Solanaceae Kc ini 0.6, Kc mid 1.15, Kc end 0.80; Sweet peppers (bell) Kc mid 1.05, Kc end 0.90, h 0.7 m; Tomato Kc mid 1.15, Kc end 0.70-0.90, h 0.6 m. Footnote: on stakes, peppers about 1.15 and tomatoes about 1.20.
- Table 11 (Ch. 6): the tomato rows (30/40/40/25 = 135, 35/40/50/30 = 155, 25/40/60/30 = 155, 35/45/70/30 = 180 days, and a Mediterranean row of 145 days).
- Table 22 (Ch. 8): sweet peppers (bell) Zr 0.5-1.0 m, p 0.30; tomato Zr 0.7-1.5 m, p 0.40.
- Eq. 82 (Ch. 8): TAW = 1000 (thetaFC - thetaWP) Zr.

Equations that were images, now read:
- Eq. 59 (Ch. 6): `Kc ini = Kc ini(Fig 29) + ((I - 10) / (40 - 10)) [Kc ini(Fig 30) - Kc ini(Fig 29)]`, I = infiltration depth in mm (10 to 40).
- Eq. 62 (Ch. 6): `Kc mid = Kc mid(Tab) + [0.04 (u2 - 2) - 0.004 (RHmin - 45)] (h / 3)^0.3`.
- Eq. 65 (Ch. 6): `Kc end = Kc end(Tab) + [0.04 (u2 - 2) - 0.004 (RHmin - 45)] (h / 3)^0.3`, applied only when Kc end(Tab) > 0.45.
- Eq. 66 (Ch. 6): `Kc i = Kc prev + [(i - SUM(L prev)) / L stage] (Kc next - Kc prev)`. Linear interpolation of Kc on day i of a growth stage: i is the day number in the season, SUM(L prev) the sum of the lengths of the previous stages, L stage the length of the current stage.
- Eq. 84 (Ch. 8): `Ks = (TAW - Dr) / (TAW - RAW) = (TAW - Dr) / ((1 - p) TAW)` when Dr > RAW. Ks = 1 when Dr <= RAW.

Still not read, and not needed for this planner: Eq. 89-93 (salinity) and the daily numeric rows of Annex 8 (a dry-bean dual-Kc example, not tomato or pepper).

What this means for the planner:
- The climate adjustment (Eq. 62 and 65) needs wind speed u2 and minimum humidity RHmin. weather-service gives only ET0 and rain, so the adjustment cannot be applied. Use the table values (standard climate) and state this as a limitation.
- Eq. 66 is needed: it gives the daily Kc between the stage values.
- Ks (Eq. 84) matters only when depletion exceeds RAW. A planner that irrigates at or before RAW keeps Ks = 1; the design must say what it does when the first day already starts beyond RAW.
