// A band's height as a CSS variable on <html> while the band is mounted (design 13 section 8.3): the job bar publishes
// `--jobs-bar`, the Verify flag notice `--flag-notice`, and Verify's page strip gives that height back on a short window.
import { useLayoutEffect, type RefObject } from "react";

export function usePublishedHeight(ref: RefObject<HTMLElement>, name: `--${string}`): void {
  useLayoutEffect(() => {
    const el = ref.current;
    const root = document.documentElement;
    if (!el) return;
    const measure = (): void => root.style.setProperty(name, `${Math.ceil(el.getBoundingClientRect().height)}px`);
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => {
      ro?.disconnect();
      root.style.removeProperty(name);
    };
  }, [ref, name]);
}
