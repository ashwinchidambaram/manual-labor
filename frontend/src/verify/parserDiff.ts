// Parser disagreement highlights (design 09 V7). Pure token diff plus a mapping onto OCR word boxes.
import { diffArrays } from "diff";
import type { OcrWord } from "../api/schema";

export const PAIRS: [string, string][] = [
  ["pymupdf", "docling"],
  ["ocr", "ocr_alt"],
  ["docx", "docling"],
];

/** First parser pair for which both texts exist, in the scoring order. */
export function pickPair(texts: Record<string, string>): { a: string; b: string; ta: string; tb: string } | null {
  for (const [a, b] of PAIRS) if (a in texts && b in texts) return { a, b, ta: texts[a], tb: texts[b] };
  return null;
}

export interface Span {
  text: string;
  differs: boolean;
}

const tokens = (t: string): string[] => t.split(/(\s+)/).filter((x) => x !== "");
const isSpace = (t: string): boolean => /^\s+$/.test(t);
const same = (x: string, y: string): boolean => (isSpace(x) && isSpace(y)) || x === y;

/** Spans of both texts; `differs` marks the words that exist in one parser's text only (word-level, so 0.25 stays whole). */
export function parserDiff(ta: string, tb: string): { a: Span[]; b: Span[] } {
  const A = tokens(ta);
  const B = tokens(tb);
  const a: Span[] = [];
  const b: Span[] = [];
  let i = 0;
  let j = 0;
  const push = (out: Span[], text: string, differs: boolean): void => {
    const last = out[out.length - 1];
    if (last && last.differs === differs) last.text += text;
    else out.push({ text, differs });
  };
  for (const part of diffArrays(A, B, { comparator: same })) {
    const n = part.count ?? part.value.length;
    if (part.added) {
      for (const t of B.slice(j, j + n)) push(b, t, true);
      j += n;
    } else if (part.removed) {
      for (const t of A.slice(i, i + n)) push(a, t, true);
      i += n;
    } else {
      for (const t of A.slice(i, i + n)) push(a, t, false);
      for (const t of B.slice(j, j + n)) push(b, t, false);
      i += n;
      j += n;
    }
  }
  return { a, b };
}

const norm = (s: string): string => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/** Words (with a disagree flag) of the first parser's text, whitespace-separated. */
export function disagreeWords(ta: string, tb: string): { word: string; differs: boolean }[] {
  const out: { word: string; differs: boolean }[] = [];
  for (const s of parserDiff(ta, tb).a) {
    for (const w of s.text.split(/\s+/)) if (w !== "") out.push({ word: w, differs: s.differs });
  }
  return out;
}

/**
 * Map disagreeing words onto OCR word boxes, preserving order: each word is matched to the next OCR word with the same
 * normalised text (within a small look-ahead); words without a match are skipped.
 */
export function mapToOcrWords(words: { word: string; differs: boolean }[], ocr: OcrWord[]): OcrWord[] {
  const hits: OcrWord[] = [];
  let j = 0;
  for (const w of words) {
    const n = norm(w.word);
    if (n === "") continue;
    for (let k = j; k < Math.min(ocr.length, j + 6); k++) {
      if (norm(ocr[k].text) === n) {
        if (w.differs && ocr[k].bbox) hits.push(ocr[k]);
        j = k + 1;
        break;
      }
    }
  }
  return hits;
}

/** Display names of the readers behind each parser text. */
export const READER: Record<string, string> = {
  pymupdf: "PDF text layer",
  docling: "Layout parser",
  ocr: "OCR",
  ocr_alt: "Second OCR",
  docx: "Word file",
};

export interface LinePair {
  /** 1-based line number in the first reading */
  line: number;
  a: string;
  b: string;
}

const squash = (s: string): string => s.replace(/\s+/g, " ").trim();

/**
 * The lines where two readings differ (design 13 F4), so they can be shown as two readable lines instead of a log
 * string. Lines are compared with whitespace collapsed; a line present in one reading only pairs with an empty one.
 */
export function readingLines(ta: string, tb: string): LinePair[] {
  const A = ta.split("\n");
  const B = tb.split("\n");
  const out: LinePair[] = [];
  let i = 0;
  let j = 0;
  let pendingA: string[] = [];
  let pendingB: string[] = [];
  let startLine = 1;
  const flush = (): void => {
    const n = Math.max(pendingA.length, pendingB.length);
    for (let k = 0; k < n; k++) out.push({ line: startLine + k, a: pendingA[k] ?? "", b: pendingB[k] ?? "" });
    pendingA = [];
    pendingB = [];
  };
  for (const part of diffArrays(A, B, { comparator: (x, y) => squash(x) === squash(y) })) {
    const n = part.count ?? part.value.length;
    if (part.removed) {
      if (!pendingA.length && !pendingB.length) startLine = i + 1;
      pendingA.push(...A.slice(i, i + n));
      i += n;
    } else if (part.added) {
      if (!pendingA.length && !pendingB.length) startLine = i + 1;
      pendingB.push(...B.slice(j, j + n));
      j += n;
    } else {
      flush();
      i += n;
      j += n;
    }
  }
  flush();
  return out;
}
