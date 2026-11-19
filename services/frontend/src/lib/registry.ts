import "server-only";
import { serviceUrl, TIMEOUTS_MS } from "./config";
import { getJson } from "./http";
import type { Farm, Plot } from "./types";

export function listFarms(): Promise<Farm[]> {
  return getJson<Farm[]>(`${serviceUrl("registry")}/v1/farms`, TIMEOUTS_MS.registry);
}

export function listPlots(): Promise<Plot[]> {
  return getJson<Plot[]>(`${serviceUrl("registry")}/v1/plots`, TIMEOUTS_MS.registry);
}

export function getPlot(id: string): Promise<Plot> {
  return getJson<Plot>(
    `${serviceUrl("registry")}/v1/plots/${encodeURIComponent(id)}`,
    TIMEOUTS_MS.registry,
  );
}
