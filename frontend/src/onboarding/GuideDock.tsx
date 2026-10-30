import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSources } from "../api/queries";
import GuidePanel from "./GuidePanel";
import { GUIDE_STEPS, stepForPath } from "./guide";

const SHEET_VAR = "--guide-sheet";

/**
 * Mounts the guide panel for the current route. Arriving on a screen shows its card unless the reader paged
 * manually in the last 5 s. Below the xl breakpoint the panel is a bottom sheet; its height is published as a CSS
 * variable so the page can pad for it and the Verify action bar stays above it.
 */
export default function GuideDock({ path, mock, onHide }: { path: string; mock: boolean; onHide: () => void }) {
  const [index, setIndex] = useState(() => stepForPath(path));
  const pagedAt = useRef(0);
  useEffect(() => {
    if (Date.now() - pagedAt.current > 5000) setIndex(stepForPath(path));
  }, [path]);
  const sources = useSources();
  const scanned = (sources.data ?? []).some((s) => s.kind === "scanned_pdf");
  const step = GUIDE_STEPS[index];
  const notes = [
    ...(mock ? ["Mock models: model results in this project are placeholders."] : []),
    ...(step.id === "verify" && scanned ? ["Scanned pages: their text comes from OCR, so more of their blocks are queued."] : []),
  ];

  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const root = document.documentElement;
    if (!el) return;
    const measure = (): void => {
      const sheet = getComputedStyle(el).position === "fixed";
      root.style.setProperty(SHEET_VAR, sheet ? `${Math.ceil(el.getBoundingClientRect().height)}px` : "0px");
    };
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
      root.style.removeProperty(SHEET_VAR);
    };
  }, []);

  const page = (d: number): void => {
    pagedAt.current = Date.now();
    setIndex((i) => Math.min(GUIDE_STEPS.length - 1, Math.max(0, i + d)));
  };
  const hide = (): void => {
    // focus is only touched when it was inside the panel (it would otherwise be lost with it): it goes to Help
    if (ref.current?.contains(document.activeElement)) document.querySelector<HTMLElement>("[data-help-button]")?.focus();
    onHide();
  };
  return <GuidePanel ref={ref} step={step} index={index} total={GUIDE_STEPS.length} onPrev={() => page(-1)} onNext={() => page(1)} onHide={hide} notes={notes} />;
}
