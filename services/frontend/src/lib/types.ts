export type Farm = { id: string; name: string };

export type Plot = {
  id: string;
  farm_id: string;
  name: string;
  area_m2: number;
  crop_id: string;
  planting_date: string;
  soil_id: string;
  row_spacing_m: number;
  emitter_spacing_m: number;
  emitter_id: string;
  lat: number;
  lon: number;
};

export type Warning =
  | { code: "planting_date_past_cycle"; days_past_cycle: number }
  | { code: "planting_date_in_future"; days_until_planting: number }
  | { code: "forecast_short"; days_requested: number; days_received: number };

export type PlanDay = {
  date: string; // plain local date, YYYY-MM-DD
  stage: string;
  stale: boolean;
  et0_mm: number;
  kc: number;
  etc_mm: number;
  rain_mm: number;
  rain_counted_mm: number;
  irrigation_mm: number;
  litres: number;
  run_minutes: number;
  capped: boolean;
  bucket_mm: number;
  trigger_mm: number;
};

export type Plan = {
  plot_id: string;
  crop_id: string;
  area_m2: number;
  flow_lph: number;
  taw_mm: number;
  assumed_start: { rule: string; bucket_mm: number };
  forecast: { source: string; fetched_at: string };
  warnings: Array<Warning | { code: string }>;
  days: PlanDay[];
};
