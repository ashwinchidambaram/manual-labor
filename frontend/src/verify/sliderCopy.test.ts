import { describe, expect, it } from "vitest";
import { clampView, normalizeView, sliderCopy, stepView } from "./sliderCopy";

describe("VU9 sliderCopy", () => {
  it("explains the filter in plain words", () => {
    expect(sliderCopy(null, 0.85, 0)).toBe("Only blocks under the 0.85 threshold");
    expect(sliderCopy(0.95, 0.85, 3)).toBe("Showing 3 auto-approved blocks below 0.95");
    expect(sliderCopy(0.9, 0.85, 1)).toBe("Showing 1 auto-approved block below 0.90");
    expect(sliderCopy(1, 0.85, 12, true)).toBe("Showing 12+ auto-approved blocks below 1.00");
  });
  it("clamps to [T, 1] and treats T as off", () => {
    expect(clampView(0.2, 0.85)).toBe(0.85);
    expect(clampView(1.4, 0.85)).toBe(1);
    expect(normalizeView(0.85, 0.85)).toBeNull();
    expect(normalizeView(0.9, 0.85)).toBe(0.9);
    expect(normalizeView(null, 0.85)).toBeNull();
  });
  it("steps by 0.05 and returns to null at the threshold", () => {
    expect(stepView(null, 1, 0.85)).toBe(0.9);
    expect(stepView(0.9, 1, 0.85)).toBe(0.95);
    expect(stepView(1, 1, 0.85)).toBe(1);
    expect(stepView(0.9, -1, 0.85)).toBeNull();
    expect(stepView(null, -1, 0.85)).toBeNull();
  });
});
