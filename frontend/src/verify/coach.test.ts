import { describe, expect, it } from "vitest";
import type { BlockDetail } from "../api/schema";
import { coachFor } from "./coach";
import { readingLines } from "./parserDiff";

const detail = (over: Partial<BlockDetail["block"]> = {}, why: BlockDetail["why"] = [], texts: Record<string, string> = {}): BlockDetail =>
  ({
    block: { id: "b-x-p001-01", doc_id: "x", page: 1, type: "paragraph", raw_text: "", clean_text: "", status: "queued", has_numeric_spec: false, faithfulness: { passed: true }, ...over },
    why,
    parser_texts: texts,
  }) as unknown as BlockDetail;

describe("readingLines", () => {
  it("pairs the differing lines by their line number in the first reading", () => {
    expect(readingLines("a\nb c\nd", "a\nb x\nd")).toEqual([{ line: 2, a: "b c", b: "b x" }]);
    expect(readingLines("a\n+0.05 using\nd", "a\n.i e\nd")[0]).toEqual({ line: 2, a: "+0.05 using", b: ".i e" });
    expect(readingLines("same  text", "same text")).toEqual([]);
    expect(readingLines("a\nb", "a")).toEqual([{ line: 2, a: "b", b: "" }]);
  });
});

describe("coachFor: only what this block's signals say", () => {
  it("quotes the start of the line the user can see, then the word and the numbers (never a bare line number)", () => {
    const d = detail(
      { has_numeric_spec: true },
      [
        { kind: "signal", name: "parser_agreement", value: 0.12, critical: true, detail: "x" },
        { kind: "signal", name: "ocr_min", value: 0.9, critical: true, detail: "min 0.899 at '4471-A'; 68 words" },
      ],
      { ocr: "a\nSet part 4471-A to 0.25 mm now\nc", ocr_alt: "a\n.i e\nc" },
    );
    expect(coachFor(d).text).toBe('Compare the line that starts "Set part 4471-A to…", the word "4471-A" and every number with the page, then decide.');
  });
  it("textlayer_vs_ocr points at the text layer against OCR, not at the first parser pair", () => {
    const d = detail(
      { raw_source: "pymupdf" } as never,
      [{ kind: "signal", name: "textlayer_vs_ocr", value: 0.7, critical: false, detail: "text layer vs OCR 0.7" }],
      { pymupdf: "Torque 35 N·m\nok", docling: "Torque 35 N·m\nok", ocr: "Torque 36 N·m\nok" },
    );
    expect(coachFor(d).text).toBe('Compare the line that starts "Torque 35 N·m" with the page, then decide.');
  });
  it("two differing lines are both quoted; more than two point at the readings list", () => {
    const two = detail({}, [{ kind: "signal", name: "parser_agreement", value: 0.5, critical: true, detail: "pymupdf vs docling 0.5" }], {
      pymupdf: "one a\ntwo b\nthree",
      docling: "one x\ntwo y\nthree",
    });
    expect(coachFor(two).text).toBe('Compare the lines that start "one a" and "two b" with the page, then decide.');
    const three = detail({}, [{ kind: "signal", name: "parser_agreement", value: 0.5, critical: true, detail: "pymupdf vs docling 0.5" }], {
      pymupdf: "a1\nb1\nc1",
      docling: "a2\nb2\nc2",
    });
    expect(coachFor(three).text).toBe('Compare the 3 lines under "The two readings differ" with the page, then decide.');
  });
  it("a passed signal is never named", () => {
    const d = detail({}, [{ kind: "signal", name: "parser_agreement", value: 1, critical: true, detail: "same" }], { ocr: "a", ocr_alt: "a" });
    expect(coachFor(d).text).toBe("Compare the text with the page, then decide.");
  });
  it("a failed cleanup points at the diff; a stale approval says so", () => {
    expect(coachFor(detail({ faithfulness: { passed: false } } as never)).text).toMatch(/^Cleanup changed words/);
    expect(coachFor(detail({}, [{ kind: "stale", name: "changed since approval", value: null, critical: false }])).text).toMatch(/changed since you approved/);
  });
  it("always offers the five decisions", () => {
    expect(coachFor(undefined).keys?.map((k) => k.id)).toEqual(["vApprove", "vEdit", "vFlag", "vSkip", "vBack"]);
  });
});
