-- PostgreSQL schema for registry-service: the five tables, no rows.
-- The rows are in sql/seed_data.sql. scripts/seed.py applies both files in one transaction.
-- No IF NOT EXISTS and no schema name: a second run fails, and the test fixtures reuse this file.

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
