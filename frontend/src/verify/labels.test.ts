import { describe, expect, it } from "vitest";
import type { BlockDetail } from "../api/schema";
import { makeBlockDetail, makeQueueItem } from "../test/verifyFake";
import { cardExcerpt, cardTitle, cutExcerpt, faithHeldSentence, weakestFromDetail } from "./labels";
import { itemFromDetail } from "./useVerifyState";

describe("cardTitle", () => {
  it("section heading, else the document, else the page and type", () => {
    expect(cardTitle(" 4.1 Coolant Service ", "manual.pdf", 9, "paragraph")).toBe("4.1 Coolant Service");
    expect(cardTitle(null, "manual.pdf", 9, "paragraph")).toBe("manual.pdf");
    expect(cardTitle("  ", " ", 9, "list_item")).toBe("Page 9, list item");
  });
});

describe("weakestFromDetail", () => {
  it("reads the word the OCR signal recorded, and nothing else", () => {
    expect(weakestFromDetail("min 0.899 at '4471-A'; 68 words")).toBe("4471-A");
    expect(weakestFromDetail("min 0.5 at 'M8'")).toBe("M8");
    expect(weakestFromDetail("mean over 12 words")).toBeNull();
    expect(weakestFromDetail(null)).toBeNull();
  });
});

describe("faithHeldSentence", () => {
  it("takes the sentence from the scorer's detail", () => {
    expect(faithHeldSentence("cleanup candidate rejected (numeric); kept deterministic result")).toMatch(/^A model's cleanup was rejected/);
    expect(faithHeldSentence("passed via evidence-backed reorder")).toMatch(/reading-order fix/);
    expect(faithHeldSentence(null)).toBe("Cleanup passed with a note");
  });
});

describe("cardExcerpt: the server's card rule (manuallabor/state/card.py)", () => {
  it("normalises whitespace and cuts at a word boundary with an ellipsis, at 80 characters", () => {
    expect(cutExcerpt("  a\n b  ")).toBe("a b");
    const long = "Set the clearance at the control board to 0.25 mm using a feeler gauge, then tighten the two screws firmly.";
    const out = cutExcerpt(long);
    expect(out.length).toBeLessThanOrEqual(80);
    expect(out.endsWith("…")).toBe(true);
    expect(long.startsWith(out.slice(0, -1))).toBe(true);
    expect(out.slice(-2, -1)).not.toBe(" ");
  });
  it("figure: its caption, else 'Figure on page N'; table: its first row", () => {
    expect(cardExcerpt({ type: "figure", page: 4, raw_text: "" }, " Figure 2  Pump ")).toBe("Figure 2 Pump");
    expect(cardExcerpt({ type: "figure", page: 4, raw_text: "" }, null)).toBe("Figure on page 4");
    const table = { cells: [{ row: 1, col: 0, text: "x" }, { row: 0, col: 1, text: "Torque" }, { row: 0, col: 0, text: "Part" }] };
    expect(cardExcerpt({ type: "table", page: 1, raw_text: "raw", table })).toBe("Part · Torque");
    expect(cardExcerpt({ type: "paragraph", page: 1, raw_text: "raw", clean_text: "clean  text" })).toBe("clean text");
  });
  it("the pinned card built from a detail matches the list's excerpt and keeps a known section title", () => {
    const it0 = makeQueueItem(1, { section_title: "4.1 Coolant Service", weakest_word: "4471-A" });
    const d: BlockDetail = makeBlockDetail(it0, {}, { clean_text: "Do   not operate\nthe unit." });
    const pinned = itemFromDetail(d, it0);
    expect(pinned.excerpt).toBe("Do not operate the unit.");
    expect(pinned.section_title).toBe("4.1 Coolant Service");
    expect(pinned.weakest_word).toBe("4471-A");
    expect(itemFromDetail(d).section_title).toBeNull();
  });
});
