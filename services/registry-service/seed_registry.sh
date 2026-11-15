#!/usr/bin/env bash
# Build a small SQLite file for registry-service.
# Safe to run again: it deletes the file and writes a fresh one.
#
# Usage, from services/registry-service:
#   bash seed_registry.sh
#   bash seed_registry.sh /path/to/registry.db

set -euo pipefail

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is not installed." >&2
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
db="${1:-registry.db}"
rm -f "$db"

sqlite3 "$db" <<'SQL'
PRAGMA foreign_keys = ON;

CREATE TABLE farms (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE crops (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE soils (
  id                         TEXT PRIMARY KEY,
  name                       TEXT NOT NULL,
  available_water_mm_per_m   INTEGER NOT NULL
);

CREATE TABLE emitters (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  flow_lph REAL NOT NULL
);

CREATE TABLE plots (
  id                 TEXT PRIMARY KEY,
  farm_id            TEXT NOT NULL REFERENCES farms(id),
  name               TEXT NOT NULL,
  area_m2            REAL NOT NULL,
  crop_id            TEXT NOT NULL REFERENCES crops(id),
  planting_date      TEXT NOT NULL,
  soil_id            TEXT NOT NULL REFERENCES soils(id),
  row_spacing_m      REAL NOT NULL,
  emitter_spacing_m  REAL NOT NULL,
  emitter_id         TEXT NOT NULL REFERENCES emitters(id),
  lat                REAL NOT NULL,
  lon                REAL NOT NULL,
  UNIQUE (farm_id, name)
);
SQL

# The rows are shared with the PostgreSQL seed command: sql/seed_data.sql.
{ echo "PRAGMA foreign_keys = ON;"; cat "$here/sql/seed_data.sql"; } | sqlite3 -bail "$db"

echo "Wrote $db"
echo "  2 farms, 4 plots, 2 crops, 3 soils, 4 emitters"
