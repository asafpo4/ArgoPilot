-- The 15 sample rows: 2 crops, 3 soils, 4 emitters, 2 farms, 4 plots.
-- One source for both backends: seed_registry.sh (SQLite) and scripts/seed.py (PostgreSQL) load
-- this file after they create the tables. Insert order follows the foreign keys.

INSERT INTO crops (id, name) VALUES
  ('tomato', 'Tomato'),
  ('bell-pepper', 'Bell pepper');

INSERT INTO soils (id, name, available_water_mm_per_m) VALUES
  ('sand', 'Sand', 83),
  ('loam', 'Loam', 175),
  ('clay-loam', 'Clay loam', 200);

INSERT INTO emitters (id, name, flow_lph) VALUES
  ('dripnet-pc-0.6', 'DripNet PC', 0.6),
  ('dripnet-pc-1.0', 'DripNet PC', 1.0),
  ('dripnet-pc-1.6', 'DripNet PC', 1.6),
  ('dripnet-pc-2.0', 'DripNet PC', 2.0);

INSERT INTO farms (id, name) VALUES
  ('b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001', 'Demo cooperative'),
  ('a9c1e4b2-6f70-4d8e-a144-3f8b5c904004', 'East farm');

INSERT INTO plots (
  id, farm_id, name, area_m2, crop_id, planting_date, soil_id,
  row_spacing_m, emitter_spacing_m, emitter_id, lat, lon
) VALUES
  (
    'c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002',
    'b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001',
    'North block', 1000, 'tomato', '2026-03-01', 'loam',
    1.5, 0.4, 'dripnet-pc-1.0', 31.25, 34.79
  ),
  (
    'd9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003',
    'b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001',
    'East block', 800, 'bell-pepper', '2026-04-12', 'clay-loam',
    1.5, 0.4, 'dripnet-pc-1.6', 31.26, 34.80
  ),
  (
    'e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004',
    'a9c1e4b2-6f70-4d8e-a144-3f8b5c904004',
    'West block', 1500, 'tomato', '2026-02-15', 'sand',
    1.5, 0.4, 'dripnet-pc-0.6', 31.40, 34.60
  ),
  (
    'f1c6a4e3-7051-4d8c-9e55-4a9b6c025005',
    'a9c1e4b2-6f70-4d8e-a144-3f8b5c904004',
    'Greenhouse', 400, 'bell-pepper', '2026-05-01', 'loam',
    1.2, 0.3, 'dripnet-pc-2.0', 31.41, 34.61
  );
