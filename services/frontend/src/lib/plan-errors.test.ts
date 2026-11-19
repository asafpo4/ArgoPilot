import { describe, expect, it } from "vitest";
import { describeFailure, parseRetryAfter } from "./plan-errors";

const http = (status: number, code?: string, detail?: string, retryAfter?: number) =>
  describeFailure({ kind: "http", status, code, detail, retryAfter });

describe("describeFailure", () => {
  it("names the failing service from the two fixed details", () => {
    expect(http(503, "UPSTREAM_UNAVAILABLE", "registry-service unavailable", 5).title).toBe(
      "Registry service is unavailable",
    );
    expect(http(503, "UPSTREAM_UNAVAILABLE", "weather-service unavailable").title).toBe(
      "Weather service is unavailable",
    );
    expect(http(503, "UPSTREAM_UNAVAILABLE", "weather-service unavailable", 7).hint).toContain("7 seconds");
  });

  it("gives a generic message for any other detail and never echoes it", () => {
    const v = http(503, "UPSTREAM_UNAVAILABLE", "database at 10.0.0.5 exploded");
    expect(v.title).toBe("A service is unavailable");
    expect(JSON.stringify(v)).not.toContain("10.0.0.5");
  });

  it("maps 404, network, invalid and the rest", () => {
    expect(http(404, "NOT_FOUND", "Plot not found")).toMatchObject({ title: "Plot not found", backToHome: true });
    expect(describeFailure({ kind: "network" }).title).toBe("Planner service is unavailable");
    expect(describeFailure({ kind: "invalid" }).title).toBe("Something went wrong");
    expect(http(500, "UNAVAILABLE", "Internal server error").title).toBe("Something went wrong");
    expect(http(503, "OTHER", "registry-service unavailable").title).toBe("Something went wrong");
  });
});

describe("parseRetryAfter", () => {
  it("accepts a whole number from 1 to 60 only", () => {
    expect(parseRetryAfter("5")).toBe(5);
    expect(parseRetryAfter("60")).toBe(60);
    expect(parseRetryAfter("0")).toBeUndefined();
    expect(parseRetryAfter("61")).toBeUndefined();
    expect(parseRetryAfter("Wed, 21 Oct")).toBeUndefined();
    expect(parseRetryAfter(null)).toBeUndefined();
  });
});
