import "server-only";
import { serviceUrl, TIMEOUTS_MS, type ServiceName } from "./config";

export type Health = Record<ServiceName, boolean>;

async function isUp(name: ServiceName): Promise<boolean> {
  try {
    const res = await fetch(`${serviceUrl(name)}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUTS_MS.health),
    });
    return res.ok;
  } catch {
    return false; // down, a missing variable or a timeout: all show as down, never break the page
  }
}

/** Checks the three services in parallel. Never throws. */
export async function checkHealth(): Promise<Health> {
  const [registry, weather, planner] = await Promise.all([
    isUp("registry"),
    isUp("weather"),
    isUp("planner"),
  ]);
  return { registry, weather, planner };
}
