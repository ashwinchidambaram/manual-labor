// A media query as React state, for the few layout choices CSS cannot make on its own: which parent holds an element
// (design 13 section 9.2: Verify's whole page moves into its own column from `vast`). Everything else is CSS.
import { useSyncExternalStore } from "react";

/** The `vast` screen of tailwind.config.js. */
export const VAST_QUERY = "(min-width: 2400px)";

const supported = (): boolean => typeof window !== "undefined" && typeof window.matchMedia === "function";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (!supported()) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener?.("change", onChange);
      return () => mq.removeEventListener?.("change", onChange);
    },
    () => supported() && window.matchMedia(query).matches,
    () => false,
  );
}
