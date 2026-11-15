-- PostgreSQL schema for registry-service: five tables and the three catalogues.
-- No demo farms or plots; see sql/demo_data.sql for local use.
-- Run: psql "${DATABASE_URL:?DATABASE_URL is not set}" --single-transaction -v ON_ERROR_STOP=1 -f sql/postgres_schema.sql

CREATE TABLE farms (
  id   TEXT COLLATE "C" PRIMARY KEY,
  name TEXT COLLATE "C" NOT NULL
);

CREATE TABLE crops (
  id   TEXT COLLATE "C" PRIMARY KEY,
  name TEXT COLLATE "C" NOT NULL
);

CREATE TABLE soils (
  id                         TEXT COLLATE "C" PRIMARY KEY,
  name                       TEXT COLLATE "C" NOT NULL,
  available_water_mm_per_m   INTEGER NOT NULL
);

CREATE TABLE emitters (
  id       TEXT COLLATE "C" PRIMARY KEY,
  name     TEXT COLLATE "C" NOT NULL,
  flow_lph DOUBLE PRECISION NOT NULL
);

CREATE TABLE plots (
  id                 TEXT COLLATE "C" PRIMARY KEY,
  farm_id            TEXT COLLATE "C" NOT NULL REFERENCES farms(id),
  name               TEXT COLLATE "C" NOT NULL,
  area_m2            DOUBLE PRECISION NOT NULL,
  crop_id            TEXT COLLATE "C" NOT NULL REFERENCES crops(id),
  planting_date      TEXT COLLATE "C" NOT NULL,
  soil_id            TEXT COLLATE "C" NOT NULL REFERENCES soils(id),
  row_spacing_m      DOUBLE PRECISION NOT NULL,
  emitter_spacing_m  DOUBLE PRECISION NOT NULL,
  emitter_id         TEXT COLLATE "C" NOT NULL REFERENCES emitters(id),
  lat                DOUBLE PRECISION NOT NULL,
  lon                DOUBLE PRECISION NOT NULL,
  UNIQUE (farm_id, name)
);

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
