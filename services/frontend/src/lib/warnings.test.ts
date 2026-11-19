import { describe, expect, it } from "vitest";
import { warningText } from "./warnings";

describe("warningText", () => {
  it("builds plain text from the codes and numbers", () => {
    expect(warningText({ code: "planting_date_past_cycle", days_past_cycle: 116 })).toContain("116 days past");
    expect(warningText({ code: "planting_date_in_future", days_until_planting: 1 })).toContain("1 day away");
    expect(warningText({ code: "forecast_short", days_requested: 7, days_received: 5 })).toContain("5 of 7 days");
  });
  it("skips unknown codes and bad numbers, never shows raw data", () => {
    expect(warningText({ code: "something_new", x: 1 })).toBeNull();
    expect(warningText({ code: "forecast_short", days_requested: "7", days_received: 5 })).toBeNull();
    expect(warningText({ code: "planting_date_past_cycle" })).toBeNull();
  });
});
