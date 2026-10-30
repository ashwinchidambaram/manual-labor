import { useLayoutEffect, useRef, useState } from "react";
import type { PageRef } from "../api/schema";
import { Keycap } from "../onboarding/Copy";
import { keyLabel } from "../onboarding/guide";
import type { PageMarks } from "./pageMarks";
import { stripRegion } from "./pageMarks";

/** The page image is rendered at most this wide (px), so a narrow block is not blown up past the 150 dpi render. */
const MAX_PAGE_PX = 1700;

/**
 * The page, magnified to the current block (design 13 F5, owner decision D2): the block's lines at reading size,
 * directly above the extracted text, so a "±" on the page sits over the "+" in the text. Not interactive and not the
 * accessible page (that is the "Source page" region beside it); the whole page is one key away (Z).
 */
export default function PageStrip({ page, bbox, marks, pageNo }: { page: PageRef; bbox: number[]; marks: PageMarks; pageNo: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  // only a strip taller than its frame (a long table) scrolls; only then is it a tab stop, so keyboard users can pan it
  const [scrollable, setScrollable] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = (): void => setW(el.getBoundingClientRect().width);
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);
  const [rx0, ry0, rx1, ry1] = stripRegion(bbox, page);
  // fit the block's width to the strip, never past MAX_PAGE_PX for the whole page
  const scale = w > 0 ? Math.min(w / Math.max(1, rx1 - rx0), MAX_PAGE_PX / page.width) : 0;
  const box = (b: number[]): React.CSSProperties => ({
    position: "absolute",
    left: (b[0] - rx0) * scale,
    top: (b[1] - ry0) * scale,
    width: (b[2] - b[0]) * scale,
    height: (b[3] - b[1]) * scale,
    pointerEvents: "none",
  });
  const height = (ry1 - ry0) * scale;
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setScrollable(el.scrollHeight > el.clientHeight + 1);
  }, [height, w]);
  const legend = [marks.boxes.length || marks.whole ? "shaded" : null, marks.weakest ? "dashed" : null].filter(Boolean);
  return (
    <figure className="m-0 flex min-w-0 flex-1 flex-col gap-2" data-testid="page-strip">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">
          The page, at this block<span className="wide:hidden"> · page {pageNo}</span>
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {legend.includes("shaded") ? (
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-2.5 w-3.5 rounded-[2px]" style={{ background: "rgb(238 192 91 / 0.6)" }} />
              where the readings differ
            </span>
          ) : null}
          {legend.includes("dashed") ? (
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-2.5 w-3.5 rounded-[2px] outline-dashed outline-[1.5px] outline-needs-ink" />
              least certain word
            </span>
          ) : null}
        </span>
        {/* below `wide` the small page locator is left out; the whole page is still one key away */}
        <span className="flex items-center gap-1 text-xs text-muted wide:hidden">
          <Keycap>{keyLabel("vZoom")}</Keycap> whole page
        </span>
      </figcaption>
      <div
        ref={ref}
        tabIndex={scrollable ? 0 : undefined}
        role={scrollable ? "group" : undefined}
        aria-label={scrollable ? "The page, magnified to this block" : undefined}
        className="max-h-[min(34vh,17rem)] overflow-auto rounded-xl border border-line bg-page shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
      >
        {scale > 0 ? (
          <div role="img" aria-label={`Page ${pageNo}, magnified to this block`} className="relative overflow-hidden" style={{ height }}>
            <img
              src={`${page.render_url}?dpi=150`}
              alt=""
              draggable={false}
              className="pointer-events-none absolute max-w-none select-none"
              style={{ width: page.width * scale, left: -rx0 * scale, top: -ry0 * scale }}
            />
            {marks.whole ? (
              <div
                data-testid="strip-disagree-block"
                style={{ ...box(bbox), backgroundImage: "repeating-linear-gradient(45deg, rgb(238 192 91 / 0.45) 0 4px, transparent 4px 8px)" }}
              />
            ) : null}
            {marks.boxes.map((b, i) => (
              <div key={i} data-testid="strip-disagree-word" style={{ ...box(b), background: "rgb(238 192 91 / 0.42)", borderRadius: 2 }} />
            ))}
            {marks.weakest ? (
              <div data-testid="strip-weakest" style={{ ...box(marks.weakest), outline: "2px dashed var(--needs-ink)", outlineOffset: 2, borderRadius: 2 }} />
            ) : null}
          </div>
        ) : (
          <div className="h-16" />
        )}
      </div>
    </figure>
  );
}
