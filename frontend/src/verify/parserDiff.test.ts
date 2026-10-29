import { describe, expect, it } from "vitest";
import type { OcrWord } from "../api/schema";
import { disagreeWords, mapToOcrWords, parserDiff, pickPair } from "./parserDiff";

describe("VU8 parserDiff", () => {
  it("picks the pair in scoring order", () => {
    expect(pickPair({ pymupdf: "a", docling: "b", ocr: "c", ocr_alt: "d" })).toMatchObject({ a: "pymupdf", b: "docling" });
    expect(pickPair({ ocr: "c", ocr_alt: "d" })).toMatchObject({ a: "ocr", b: "ocr_alt" });
    expect(pickPair({ docx: "x", docling: "y" })).toMatchObject({ a: "docx", b: "docling" });
    expect(pickPair({ pymupdf: "a" })).toBeNull();
  });
  it("marks the words that differ", () => {
    const d = parserDiff("set 0.25 mm now", "set 0.35 mm now");
    expect(d.a.filter((s) => s.differs).map((s) => s.text.trim())).toEqual(["0.25"]);
    expect(d.b.filter((s) => s.differs).map((s) => s.text.trim())).toEqual(["0.35"]);
    expect(disagreeWords("a b c", "a x c").map((w) => [w.word, w.differs])).toEqual([["a", false], ["b", true], ["c", false]]);
  });
  it("maps disagreeing words onto OCR boxes in order and skips the unmatched", () => {
    const w = (text: string, i: number): OcrWord => ({ text, confidence: 0.9, bbox: [i, 0, i + 1, 1] });
    const ocr = [w("set", 0), w("0.25", 1), w("mm", 2), w("now", 3)];
    const hits = mapToOcrWords(disagreeWords("set 0.25 mm gone now", "set 0.35 mm now"), ocr);
    expect(hits.map((h) => h.text)).toEqual(["0.25"]);
    expect(mapToOcrWords([{ word: "zzz", differs: true }], ocr)).toEqual([]);
  });
});
