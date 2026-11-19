import { describe, expect, it } from "vitest";
import { cropLabel, groupPlotsByFarm } from "./group";
import type { Plot } from "./types";

const plot = (id: string, farm_id: string): Plot => ({
  id, farm_id, name: id, area_m2: 1, crop_id: "tomato", planting_date: "2026-03-01",
  soil_id: "loam", row_spacing_m: 1, emitter_spacing_m: 1, emitter_id: "e", lat: 0, lon: 0,
});

describe("groupPlotsByFarm", () => {
  it("groups by farm, keeps farm order and empty farms", () => {
    const farms = [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }];
    const out = groupPlotsByFarm(farms, [plot("p1", "b"), plot("p2", "a"), plot("p3", "b")]);
    expect(out.map((g) => g.plots.map((p) => p.id))).toEqual([["p2"], ["p1", "p3"], []]);
  });
});

describe("cropLabel", () => {
  it("makes a readable label", () => {
    expect(cropLabel("bell-pepper")).toBe("Bell pepper");
    expect(cropLabel("tomato")).toBe("Tomato");
  });
});
