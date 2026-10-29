// Percent-of-page overlay geometry (design 09 V2) and crop validation.
import type { PageRef } from "../api/schema";

export type Dims = Pick<PageRef, "width" | "height">;
export type BBox = [number, number, number, number];

const pct = (n: number): string => `${Math.round(n * 1e4) / 1e4}%`;

export function rectStyle(bbox: number[], page: Dims): { left: string; top: string; width: string; height: string } {
  const [x0, y0, x1, y1] = bbox;
  return {
    left: pct((x0 / page.width) * 100),
    top: pct((y0 / page.height) * 100),
    width: pct(((x1 - x0) / page.width) * 100),
    height: pct(((y1 - y0) / page.height) * 100),
  };
}

export const MIN_SIDE = 4;

/** Crop box rules: x0 < x1, y0 < y1, inside the page, at least 4 pt on each side. */
export function validCrop(b: number[], page: Dims): string | null {
  if (b.length !== 4 || b.some((v) => !Number.isFinite(v))) return "Enter four numbers";
  const [x0, y0, x1, y1] = b;
  if (x0 < 0 || y0 < 0 || x1 > page.width || y1 > page.height) return "The box must stay inside the page";
  if (x1 - x0 < MIN_SIDE || y1 - y0 < MIN_SIDE) return `Each side must be at least ${MIN_SIDE} pt`;
  return null;
}

export type Corner = "nw" | "ne" | "sw" | "se";

/** Move a corner handle by (dx, dy) pt, clamped to the page and to the minimum box size. */
export function moveCorner(b: BBox, corner: Corner, dx: number, dy: number, page: Dims): BBox {
  let [x0, y0, x1, y1] = b;
  const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
  if (corner === "nw" || corner === "sw") x0 = clamp(x0 + dx, 0, x1 - MIN_SIDE);
  else x1 = clamp(x1 + dx, x0 + MIN_SIDE, page.width);
  if (corner === "nw" || corner === "ne") y0 = clamp(y0 + dy, 0, y1 - MIN_SIDE);
  else y1 = clamp(y1 + dy, y0 + MIN_SIDE, page.height);
  return [x0, y0, x1, y1];
}

/** Percent position of a point of the page. */
export const pointStyle = (x: number, y: number, page: Dims): { left: string; top: string } => ({
  left: pct((x / page.width) * 100),
  top: pct((y / page.height) * 100),
});
