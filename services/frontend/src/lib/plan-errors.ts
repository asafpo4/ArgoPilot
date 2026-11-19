/** What went wrong when asking the planner, as seen by the page. Holds no raw text to display. */
export type PlanFailure =
  | { kind: "network" }
  | { kind: "invalid" }
  | { kind: "http"; status: number; code?: string; detail?: string; retryAfter?: number };

export type FailureView = {
  title: string;
  hint?: string;
  backToHome?: boolean; // a retry would not help: offer the main page
};

const REGISTRY_DOWN = "registry-service unavailable";
const WEATHER_DOWN = "weather-service unavailable";

/** The planner's Retry-After, if it is a whole number of seconds from 1 to 60. */
export function parseRetryAfter(value: string | null): number | undefined {
  if (value === null || !/^\d{1,2}$/.test(value.trim())) return undefined;
  const n = Number(value.trim());
  return n >= 1 && n <= 60 ? n : undefined;
}

/**
 * Maps a failure to fixed texts. The type comes from the problem+json code.
 * The failing service comes only from the two fixed detail texts, anything else is generic.
 */
export function describeFailure(f: PlanFailure): FailureView {
  if (f.kind === "network") {
    return { title: "Planner service is unavailable", hint: "The plan cannot be calculated right now." };
  }
  if (f.kind === "http") {
    if (f.status === 404 && f.code === "NOT_FOUND") {
      return { title: "Plot not found", hint: "This plot does not exist.", backToHome: true };
    }
    if (f.status === 503 && f.code === "UPSTREAM_UNAVAILABLE") {
      const retry = f.retryAfter ? ` Try again in about ${f.retryAfter} seconds.` : "";
      if (f.detail === REGISTRY_DOWN) {
        return { title: "Registry service is unavailable", hint: `The plot data cannot be loaded.${retry}` };
      }
      if (f.detail === WEATHER_DOWN) {
        return { title: "Weather service is unavailable", hint: `The forecast cannot be loaded.${retry}` };
      }
      return { title: "A service is unavailable", hint: `The plan cannot be calculated right now.${retry}` };
    }
  }
  return { title: "Something went wrong", hint: "Try again in a moment." };
}
