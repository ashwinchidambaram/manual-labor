// What the page shows about the current block (design 09 V7, design 13 F5): the OCR words where the two readings
// differ, whether the whole block must be hatched instead, and the least certain OCR word. Pure.
import type { Block, WhyItem } from "../api/schema";
import { disagreeWords, mapToOcrWords, pickPair } from "./parserDiff";

export interface PageMarks {
  boxes: number[][];
  whole: boolean;
  /** bbox of the least certain OCR word, only when the OCR signal held the block */
  weakest: number[] | null;
}

export function pageMarks(block: Block | null, why: readonly WhyItem[] = []): PageMarks {
  if (!block) return { boxes: [], whole: false, weakest: null };
  const ocr = block.ocr_words ?? [];
  let boxes: number[][] = [];
  let whole = false;
  const pair = pickPair(block.raw_text_by_parser ?? {});
  if (pair && pair.ta !== pair.tb) {
    const hits = mapToOcrWords(disagreeWords(pair.ta, pair.tb), ocr);
    boxes = hits.map((h) => h.bbox as number[]);
    whole = hits.length === 0;
  }
  const held = why.some((w) => w.kind === "signal" && w.name === "ocr_min" && (w.value ?? 1) < 1);
  let weakest: number[] | null = null;
  if (held) {
    let min = Infinity;
    for (const w of ocr)
      if (w.bbox && w.bbox.length === 4 && w.confidence < min) {
        min = w.confidence;
        weakest = w.bbox as number[];
      }
  }
  return { boxes, whole, weakest };
}

/** The region of the page to magnify: the block plus a margin, in page points. */
export function stripRegion(bbox: number[], page: { width: number; height: number }, mx = 8, my = 3): [number, number, number, number] {
  const [x0, y0, x1, y1] = bbox;
  return [Math.max(0, x0 - mx), Math.max(0, y0 - my), Math.min(page.width, x1 + mx), Math.min(page.height, y1 + my)];
}
