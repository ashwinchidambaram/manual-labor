import { useEffect, useRef } from "react";
import { HOTKEYS, matches, type HotkeyId } from "../hotkeys";

export type HotkeyHandlers = Partial<Record<HotkeyId, (e: KeyboardEvent) => void>>;

const IGNORED = "input, textarea, select, [contenteditable='true'], [contenteditable='']";

/** Global key listener driven by the HOTKEYS map. Registered ids only. */
export function useHotkeys(handlers: HotkeyHandlers, enabled = true): void {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest(IGNORED)) return;
      const dialog = document.querySelector("[role='dialog']");
      for (const id of Object.keys(ref.current) as HotkeyId[]) {
        if (!matches(e, id)) continue;
        if (dialog && id !== "help") continue;
        const scope = HOTKEYS[id].scope;
        if (scope === "tree" && !target?.closest("[data-zone='tree']")) continue;
        if (scope === "models" && !target?.closest("[data-zone='models']")) continue;
        if (target?.closest("[aria-busy='true']") && scope !== "global") continue;
        // Space/Enter on a real button keep their native meaning.
        if ((id === "toggleRow" || id === "selectOnly") && target?.closest("button, a[href]")) continue;
        e.preventDefault();
        ref.current[id]?.(e);
        return;
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enabled]);
}
