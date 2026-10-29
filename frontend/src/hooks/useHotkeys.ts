import { useEffect, useRef } from "react";
import { HOTKEYS, MODAL_SCOPES, ZONE_OF, matches, type HotkeyId } from "../hotkeys";

export type HotkeyHandlers = Partial<Record<HotkeyId, (e: KeyboardEvent) => void>>;

const IGNORED = "input, textarea, select, [contenteditable='true'], [contenteditable='']";

/**
 * Global key listener driven by the HOTKEYS map. Registered ids only. The rules are data on the entries:
 * zone scopes (ZONE_OF), modal scopes (an open `[aria-modal='true']`, whose `data-hotkey-scope` is the only
 * scope that fires; a modal without one lets only `help` through), `allowInInputs`, `mod`, `nativeButtons`.
 */
export function useHotkeys(handlers: HotkeyHandlers, enabled = true): void {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.defaultPrevented) return;
      const target = e.target instanceof Element ? e.target : null;
      const inInput = !!target?.closest(IGNORED);
      const modal = document.querySelector("[aria-modal='true']");
      const modalScope = modal?.getAttribute("data-hotkey-scope") ?? null;
      const modified = e.ctrlKey || e.metaKey;
      for (const id of Object.keys(ref.current) as HotkeyId[]) {
        const h = HOTKEYS[id];
        if (!h || !matches(e, id)) continue;
        if (e.altKey) continue;
        if (h.mod ? !modified : modified) continue;
        if (inInput && !h.allowInInputs) continue;
        if (modal && !(modalScope ? h.scope === modalScope : id === "help")) continue;
        if (!modal && MODAL_SCOPES.has(h.scope)) continue;
        const zone = ZONE_OF[h.scope];
        if (zone && !target?.closest(`[data-zone='${zone}']`)) continue;
        if (target?.closest("[aria-busy='true']") && h.scope !== "global") continue;
        if (h.nativeButtons && target?.closest("button, a[href]")) continue;
        e.preventDefault();
        ref.current[id]?.(e);
        return;
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enabled]);
}
