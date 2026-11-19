import { afterEach, describe, expect, it } from "vitest";
import { forecastAge, formatMm, formatPlanDate, stageLabel } from "./format";

const originalTz = process.env.TZ;
afterEach(() => {
  if (originalTz === undefined) delete process.env.TZ;
  else process.env.TZ = originalTz;
});

describe("formatPlanDate", () => {
  it("formats from the string", () => {
    expect(formatPlanDate("2026-11-19")).toBe("Thu 19 Nov");
    expect(formatPlanDate("2026-01-01")).toBe("Thu 1 Jan");
    expect(formatPlanDate("2028-02-29")).toBe("Tue 29 Feb");
  });

  it("never shifts the day, whatever the machine time zone is", () => {
    for (const tz of ["America/Los_Angeles", "Pacific/Kiritimati", "Asia/Jerusalem", "UTC"]) {
      process.env.TZ = tz;
      expect(formatPlanDate("2026-11-19")).toBe("Thu 19 Nov");
      expect(formatPlanDate("2026-12-31")).toBe("Thu 31 Dec");
    }
  });

  it("returns an invalid date unchanged", () => {
    expect(formatPlanDate("19/11/2026")).toBe("19/11/2026");
    expect(formatPlanDate("2026-02-30")).toBe("2026-02-30");
  });
});

describe("forecastAge", () => {
  const now = Date.parse("2026-11-19T10:00:00Z");
  it("shows minutes, hours and days", () => {
    expect(forecastAge("2026-11-19T09:40:00Z", now)).toBe("fetched 20 minutes ago");
    expect(forecastAge("2026-11-19T09:59:00Z", now)).toBe("fetched 1 minute ago");
    expect(forecastAge("2026-11-19T09:59:50Z", now)).toBe("fetched just now");
    expect(forecastAge("2026-11-19T07:00:00Z", now)).toBe("fetched 3 hours ago");
    expect(forecastAge("2026-11-16T10:00:00Z", now)).toBe("fetched 3 days ago");
  });
  it("is null for a bad or future timestamp", () => {
    expect(forecastAge("not a date", now)).toBeNull();
    expect(forecastAge("2026-11-19T11:00:00Z", now)).toBeNull();
  });
});

describe("small formatters", () => {
  it("formats mm and stages", () => {
    expect(formatMm(2.4)).toBe("2.4 mm");
    expect(formatMm(3)).toBe("3 mm");
    expect(formatMm(60.7599)).toBe("60.76 mm");
    expect(stageLabel("after_cycle")).toBe("After cycle");
  });
});
