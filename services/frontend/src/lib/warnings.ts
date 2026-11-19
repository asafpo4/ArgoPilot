function count(v: unknown): number | null {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null;
}

function days(n: number): string {
  return `${n} day${n === 1 ? "" : "s"}`;
}

/** Plain-words text for a planner warning. Unknown codes and bad numbers give null, never raw data. */
export function warningText(w: { code: string } & Record<string, unknown>): string | null {
  switch (w.code) {
    case "planting_date_past_cycle": {
      const n = count(w.days_past_cycle);
      return n === null
        ? null
        : `The planting date is ${days(n)} past the end of the crop cycle, so these numbers are only an estimate. Update the planting date in the registry.`;
    }
    case "planting_date_in_future": {
      const n = count(w.days_until_planting);
      return n === null
        ? null
        : `The planting date is ${days(n)} away, so the crop is treated as just planted. Check the planting date in the registry.`;
    }
    case "forecast_short": {
      const asked = count(w.days_requested);
      const got = count(w.days_received);
      return asked === null || got === null
        ? null
        : `The forecast covers only ${got} of ${asked} days, so the plan is shorter.`;
    }
    default:
      return null;
  }
}
