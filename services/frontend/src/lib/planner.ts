import "server-only";
import { serviceUrl, TIMEOUTS_MS } from "./config";
import { parseRetryAfter, type PlanFailure } from "./plan-errors";
import type { Plan } from "./types";

export type PlanResult = { ok: true; plan: Plan } | { ok: false; failure: PlanFailure };

const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

function looksLikePlan(v: unknown): v is Plan {
  if (typeof v !== "object" || v === null) return false;
  const p = v as Record<string, unknown>;
  return (
    Array.isArray(p.days) &&
    Array.isArray(p.warnings) &&
    typeof p.forecast === "object" &&
    p.forecast !== null
  );
}

/** Asks the planner for a plan. Never throws: every failure is a value the page can describe. */
export async function fetchPlan(plotId: string, days: number): Promise<PlanResult> {
  let res: Response;
  try {
    res = await fetch(
      `${serviceUrl("planner")}/v1/plots/${encodeURIComponent(plotId)}/plan?days=${days}`,
      { cache: "no-store", signal: AbortSignal.timeout(TIMEOUTS_MS.plan) },
    );
  } catch {
    return { ok: false, failure: { kind: "network" } };
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }

  if (!res.ok) {
    const problem = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
    return {
      ok: false,
      failure: {
        kind: "http",
        status: res.status,
        code: str(problem.code),
        detail: str(problem.detail),
        retryAfter: parseRetryAfter(res.headers.get("retry-after")),
      },
    };
  }
  if (!looksLikePlan(body)) return { ok: false, failure: { kind: "invalid" } };
  return { ok: true, plan: body };
}
