export type ServiceName = "registry" | "weather" | "planner";

const VARS: Record<ServiceName, string> = {
  registry: "REGISTRY_URL",
  weather: "WEATHER_URL",
  planner: "PLANNER_URL",
};

/** Base URL of a service, without a trailing slash. Fails naming the variable, never a value. */
export function serviceUrl(name: ServiceName): string {
  const variable = VARS[name];
  const raw = process.env[variable];
  if (!raw || raw.trim() === "") {
    throw new Error(`${variable} is not set. Copy .env.example to .env.local.`);
  }
  try {
    const u = new URL(raw.trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error();
  } catch {
    throw new Error(`${variable} must be an http:// or https:// URL.`);
  }
  return raw.trim().replace(/\/+$/, "");
}

export const TIMEOUTS_MS = {
  registry: 5_000,
  health: 1_500,
  // The planner can take up to 16.3 s with its defaults.
  plan: 25_000,
} as const;
