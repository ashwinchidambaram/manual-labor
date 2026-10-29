import { describe, expect, it } from "vitest";
import { reasonChips, reasonsFromQueueItem, type ReasonIn } from "./reasons";

const sig = (name: string, value: number | null, critical = false): ReasonIn => ({ kind: "signal", name, value, critical });

describe("VU1 reasonChips", () => {
  it("lists critical failures first, by value", () => {
    const r = reasonChips({ why: [sig("ocr_mean", 0.7), sig("faithfulness", 0.6, true), sig("parser_agreement", 0.2, true)], hasNumeric: false });
    expect(r.reasons.map((c) => c.name)).toEqual(["parser_agreement", "faithfulness", "ocr_mean"]);
    expect(r.reasons[0].tone).toBe("critical");
  });
  it("always keeps the numeric rule chip, so criticals take at most max-1 slots", () => {
    const r = reasonChips({
      why: [sig("parser_agreement", 0.1, true), sig("ocr_min", 0.2, true), sig("faithfulness", 0.3, true)],
      hasNumeric: true,
    });
    expect(r.reasons.map((c) => c.name)).toEqual(["parser_agreement", "ocr_min", "has_numeric_spec"]);
    expect(r.reasons[r.reasons.length - 1]?.tone).toBe("rule");
    expect(r.overflow).toEqual(["cleanup changed content"]);
  });
  it("fills the remaining slots with soft signals, ascending", () => {
    const r = reasonChips({ why: [sig("ocr_mean", 0.9), sig("garbage_ratio", 0.5), sig("reading_order_risk", 0.7)], hasNumeric: false, max: 2 });
    expect(r.reasons.map((c) => c.name)).toEqual(["garbage_ratio", "reading_order_risk"]);
    expect(r.overflow).toEqual(["low OCR"]);
  });
  it("never duplicates the has_numeric_spec signal as a soft chip", () => {
    const r = reasonChips({ why: [sig("has_numeric_spec", 0), sig("ocr_mean", 0.9)], hasNumeric: true });
    expect(r.reasons.filter((c) => c.name === "has_numeric_spec")).toHaveLength(1);
    const none = reasonChips({ why: [sig("has_numeric_spec", 0)], hasNumeric: false });
    expect(none.reasons).toEqual([]);
  });
  it("turns a stale reason into a status chip and never counts it", () => {
    const r = reasonChips({ why: [{ kind: "stale", name: "changed since approval", value: null, critical: true }, sig("ocr_mean", 0.5)], hasNumeric: false, max: 1 });
    expect(r.status.map((c) => c.text)).toEqual(["changed since approval"]);
    expect(r.reasons.map((c) => c.name)).toEqual(["ocr_mean"]);
  });
  it("skips signals at 1.0 and keeps server order for null values", () => {
    const r = reasonChips({ why: [sig("ocr_mean", 1), sig("garbage_ratio", null), sig("reading_order_risk", null)], hasNumeric: false });
    expect(r.reasons.map((c) => c.name)).toEqual(["garbage_ratio", "reading_order_risk"]);
  });
  it("falls back to faithfulness and figure_method as critical without critical_reasons", () => {
    const fb = reasonsFromQueueItem(["faithfulness", "ocr_mean"], false);
    expect(fb.map((x) => x.critical)).toEqual([true, false]);
    const exact = reasonsFromQueueItem(["ocr_mean", "faithfulness"], false, 1);
    expect(exact.map((x) => x.critical)).toEqual([true, false]);
  });
});
