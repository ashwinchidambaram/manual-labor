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
  it("names the line, the word and the numbers", () => {
    const d = detail(
      { has_numeric_spec: true },
      [
        { kind: "signal", name: "parser_agreement", value: 0.12, critical: true, detail: "x" },
        { kind: "signal", name: "ocr_min", value: 0.9, critical: true, detail: "min 0.899 at '4471-A'; 68 words" },
      ],
      { ocr: "a\nb 4471-A\nc", ocr_alt: "a\n.i e\nc" },
    );
    expect(coachFor(d).text).toBe('Compare line 2, the word "4471-A" and every number with the page, then decide.');
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
