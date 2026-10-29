// Threshold view slider helpers (design 09 V3).
export const STEP = 0.05;

export const clampView = (v: number, T: number): number => Math.min(1, Math.max(T, Math.round(v * 100) / 100));

/** `null` at the project threshold: the filter is off. */
export function normalizeView(v: number | null, T: number): number | null {
  if (v === null) return null;
  const c = clampView(v, T);
  return c <= T ? null : c;
}

export const stepView = (v: number | null, dir: 1 | -1, T: number): number | null =>
  normalizeView((v ?? T) + dir * STEP, T);

const fmt = (n: number): string => n.toFixed(2);

export function sliderCopy(view: number | null, T: number, added: number, more = false, pending = false): string {
  if (view === null) return `Only blocks under the ${fmt(T)} threshold`;
  if (pending) return `Showing auto-approved blocks below ${fmt(view)}...`;
  const n = `${added}${more ? "+" : ""}`;
  return `Showing ${n} auto-approved block${added === 1 && !more ? "" : "s"} below ${fmt(view)}`;
}
