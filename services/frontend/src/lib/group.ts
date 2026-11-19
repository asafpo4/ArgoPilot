import type { Farm, Plot } from "./types";

export type FarmWithPlots = { farm: Farm; plots: Plot[] };

/** Groups plots under their farm, in the farms' order. A farm with no plots keeps an empty list. */
export function groupPlotsByFarm(farms: Farm[], plots: Plot[]): FarmWithPlots[] {
  return farms.map((farm) => ({
    farm,
    plots: plots.filter((p) => p.farm_id === farm.id),
  }));
}

/** "bell-pepper" -> "Bell pepper" */
export function cropLabel(cropId: string): string {
  const text = cropId.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
