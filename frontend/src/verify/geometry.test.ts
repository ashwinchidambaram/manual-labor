import { describe, expect, it } from "vitest";
import { moveCorner, rectStyle, validCrop } from "./geometry";

const page = { width: 612, height: 792 };

describe("VU7 geometry", () => {
  it("maps a bbox to percent of the page", () => {
    expect(rectStyle([61.2, 79.2, 306, 396], page)).toEqual({ left: "10%", top: "10%", width: "40%", height: "40%" });
  });
  it("validates crop boxes", () => {
    expect(validCrop([10, 10, 100, 100], page)).toBeNull();
    expect(validCrop([100, 10, 10, 100], page)).toMatch(/at least/);
    expect(validCrop([-1, 10, 100, 100], page)).toMatch(/inside/);
    expect(validCrop([10, 10, 700, 100], page)).toMatch(/inside/);
    expect(validCrop([10, 10, 12, 100], page)).toMatch(/at least 4 pt/);
    expect(validCrop([NaN, 10, 100, 100], page)).toMatch(/four numbers/);
  });
  it("clamps handle drags to the page and the minimum size", () => {
    expect(moveCorner([10, 10, 100, 100], "nw", -50, -50, page)).toEqual([0, 0, 100, 100]);
    expect(moveCorner([10, 10, 100, 100], "se", 900, 900, page)).toEqual([10, 10, 612, 792]);
    expect(moveCorner([10, 10, 100, 100], "ne", -500, 500, page)).toEqual([10, 96, 14, 100]);
    expect(moveCorner([10, 10, 100, 100], "sw", 5, 5, page)).toEqual([15, 10, 100, 105]);
  });
});
