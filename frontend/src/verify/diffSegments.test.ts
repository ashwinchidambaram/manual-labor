import { describe, expect, it } from "vitest";
import type { DiffOp } from "../api/schema";
import { cleanOf, diffSegments, isIdentical, numericRanges, rawOf, visualize } from "./diffSegments";
import recorded from "./recorded.diffs.json";

const op = (o: DiffOp["op"], allowed: boolean, raw: string, clean: string): DiffOp => ({
  op: o,
  allowed,
  raw,
  clean,
  raw_start: 0,
  raw_end: raw.length,
  clean_start: 0,
  clean_end: clean.length,
});
const tuple = (s: ReturnType<typeof diffSegments>[number]) => [s.kind, s.ok, s.text, s.display, s.numeric];

describe("VU2 diffSegments: the 12-row table", () => {
  const rows: [string, DiffOp, unknown[][]][] = [
    ["1 equal", op("equal", true, "abc", "abc"), [["equal", true, "abc", "abc", []]]],
    ["2 delete allowed", op("delete", true, "-\n", ""), [["del", true, "-\n", "-↵", []]]],
    ["3 insert allowed", op("insert", true, "", " "), [["ins", true, " ", "␣", []]]],
    ["4 delete violation", op("delete", false, "35", ""), [["del", false, "35", "35", [[0, 2]]]]],
    ["5 insert violation", op("insert", false, "", "36"), [["ins", false, "36", "36", [[0, 2]]]]],
    [
      "6 replace violation",
      op("replace", false, "35 N·m", "36 N·m"),
      [
        ["del", false, "35 N·m", "35␣N·m", [[0, 2]]],
        ["ins", false, "36 N·m", "36␣N·m", [[0, 2]]],
      ],
    ],
    [
      "7 replace allowed",
      op("replace", true, "\n", " "),
      [
        ["del", true, "\n", "↵", []],
        ["ins", true, " ", "␣", []],
      ],
    ],
    ["8 reorder allowed", op("reorder", true, "Step 2.", "Step 2."), [["move", true, "Step 2.", "Step␣2.", [[5, 6]]]]],
    ["9 reorder violation, clean empty", op("reorder", false, "Then oil.", ""), [["move", false, "Then oil.", "Then␣oil.", []]]],
    ["10 empty equal", op("equal", true, "", ""), []],
    ["11 insert tab", op("insert", false, "", "\t"), [["ins", false, "\t", "→", []]]],
    ["12 numeric ranges", op("equal", true, "0.25 mm ±0.05", "0.25 mm ±0.05"), [["equal", true, "0.25 mm ±0.05", "0.25 mm ±0.05", [[0, 4], [9, 13]]]]],
  ];
  for (const [name, input, expected] of rows)
    it(`row ${name}`, () => {
      expect(diffSegments([input]).map(tuple)).toEqual(expected);
    });
  it("carries the op index and keeps op order", () => {
    const segs = diffSegments([op("equal", true, "a", "a"), op("replace", true, "b", "c"), op("equal", true, "d", "d")]);
    expect(segs.map((s) => [s.opIndex, s.kind])).toEqual([
      [0, "equal"],
      [1, "del"],
      [1, "ins"],
      [2, "equal"],
    ]);
  });
});

describe("VU3 diffSegments invariants on recorded diffs", () => {
  for (const [name, r] of Object.entries(recorded)) {
    it(`${name}: raw and clean reconstruct, every op is covered`, () => {
      const ops = r.diff as DiffOp[];
      expect(rawOf(ops)).toBe(r.raw_text);
      expect(cleanOf(ops)).toBe(r.clean_text);
      const segs = diffSegments(ops);
      const covered = new Set(segs.map((s) => s.opIndex));
      ops.forEach((o, i) => {
        if ((o.op === "equal" ? o.clean : o.raw + o.clean) !== "") expect(covered.has(i), `op ${i}`).toBe(true);
      });
      expect(segs.map((s) => s.opIndex)).toEqual([...segs.map((s) => s.opIndex)].sort((a, b) => a - b));
      expect(segs.filter((s) => s.kind === "equal").map((s) => s.text).join("")).toBe(ops.filter((o) => o.op === "equal").map((o) => o.clean).join(""));
    });
  }
  it("the dehyphenation block shows the removed hyphen and line break as allowed", () => {
    const segs = diffSegments(recorded.dehyphenation.diff as DiffOp[]);
    expect(segs.some((s) => s.kind === "del" && s.ok && s.display === "-↵")).toBe(true);
  });
  it("header removal is a violation and the identical check is false", () => {
    const segs = diffSegments(recorded.headerRemoval.diff as DiffOp[]);
    expect(segs.some((s) => s.kind === "del" && !s.ok)).toBe(true);
    expect(isIdentical(recorded.headerRemoval.diff as DiffOp[])).toBe(false);
    expect(isIdentical([op("equal", true, "a", "a")])).toBe(true);
  });
});

describe("VU4 visualize and numericRanges", () => {
  it("makes whitespace visible one for one", () => {
    expect(visualize("a b\nc\td e")).toBe("a␣b↵c→d⍽e");
    expect(visualize("a b").length).toBe(3);
  });
  it("the visible-space glyph cannot be confused with a middle dot in the text itself", () => {
    expect(visualize("35 N·m")).toBe("35␣N·m");
    expect(visualize("35 N·m")).not.toBe(visualize("35·N·m"));
  });
  it("finds numbers with units, tolerances, part numbers and thousands separators", () => {
    expect(numericRanges("10A")).toEqual([[0, 2]]);
    expect(numericRanges("±0.05")).toEqual([[1, 5]]);
    expect(numericRanges("4471-A")).toEqual([[0, 4]]);
    expect(numericRanges("1,250.5 kg")).toEqual([[0, 7]]);
    expect(numericRanges("no digits")).toEqual([]);
  });
});
