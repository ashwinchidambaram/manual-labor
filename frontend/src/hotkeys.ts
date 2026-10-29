// Single hotkey map for the whole UI. Every keyboard binding lives here (design 08 section 4.1).
// Key names are `event.key` lower-cased; Space is "space"; Shift is only expressed as "shift+<letter>".

export type HotkeyScope = "global" | "scope" | "tree" | "models";

export type HotkeyId =
  | "help"
  | "goScope"
  | "goVerify"
  | "goAgent"
  | "goExport"
  | "toggleView"
  | "focusTree"
  | "focusSources"
  | "focusModels"
  | "focusSummary"
  | "splitMode"
  | "selectAll"
  | "selectNone"
  | "confirm"
  | "moveDown"
  | "moveUp"
  | "first"
  | "last"
  | "expand"
  | "collapse"
  | "toggleRow"
  | "selectOnly"
  | "selectWholeDoc";

export interface Hotkey {
  keys: string[];
  scope: HotkeyScope;
  label: string;
  when?: string;
}

export const HOTKEYS: Record<HotkeyId, Hotkey> = {
  help: { keys: ["?"], scope: "global", label: "Show or hide this help" },
  goScope: { keys: ["1"], scope: "global", label: "Go to Scope" },
  goVerify: { keys: ["2"], scope: "global", label: "Go to Verify" },
  goAgent: { keys: ["3"], scope: "global", label: "Go to Agent" },
  goExport: { keys: ["4"], scope: "global", label: "Go to Export" },
  toggleView: { keys: ["t"], scope: "scope", label: "Switch between topics and document structure" },
  focusTree: { keys: ["escape"], scope: "scope", label: "Focus the group list" },
  focusSources: { keys: ["o"], scope: "scope", label: "Focus the sources list" },
  focusModels: { keys: ["m"], scope: "scope", label: "Focus the model panel (again: back to the list)" },
  focusSummary: { keys: ["u"], scope: "scope", label: "Focus the selection summary" },
  splitMode: { keys: ["s"], scope: "scope", label: "Cycle article split: per topic / per document" },
  selectAll: { keys: ["a"], scope: "scope", label: "Select every block" },
  selectNone: { keys: ["n"], scope: "scope", label: "Clear the selection" },
  confirm: { keys: ["g"], scope: "scope", label: "Confirm scope and go to Verify" },
  moveDown: { keys: ["j", "arrowdown"], scope: "tree", label: "Next row" },
  moveUp: { keys: ["k", "arrowup"], scope: "tree", label: "Previous row" },
  first: { keys: ["home"], scope: "tree", label: "First row" },
  last: { keys: ["end"], scope: "tree", label: "Last row" },
  expand: { keys: ["arrowright", "l"], scope: "tree", label: "Expand, or go to the first child", when: "structure view" },
  collapse: { keys: ["arrowleft", "h"], scope: "tree", label: "Collapse, or go to the parent", when: "structure view" },
  toggleRow: { keys: ["space"], scope: "tree", label: "Toggle the row (partial selects the rest)" },
  selectOnly: { keys: ["enter"], scope: "tree", label: "Select only this row" },
  selectWholeDoc: { keys: ["shift+a"], scope: "tree", label: "Select the whole document of this row" },
};

/** Normalised key name of a keyboard event; "shift+x" only for letters. */
export function keyName(e: Pick<KeyboardEvent, "key" | "shiftKey">): string {
  if (e.key === " ") return "space";
  const k = e.key.toLowerCase();
  return e.shiftKey && /^[a-z]$/.test(k) ? `shift+${k}` : k;
}

export function matches(e: Pick<KeyboardEvent, "key" | "shiftKey">, id: HotkeyId): boolean {
  return HOTKEYS[id].keys.includes(keyName(e));
}

export function scopesOverlap(a: HotkeyScope, b: HotkeyScope): boolean {
  if (a === b || a === "global" || b === "global") return true;
  return a === "scope" || b === "scope";
}

export function displayKey(k: string): string {
  const map: Record<string, string> = {
    arrowdown: "Down",
    arrowup: "Up",
    arrowleft: "Left",
    arrowright: "Right",
    escape: "Esc",
    space: "Space",
    enter: "Enter",
    home: "Home",
    end: "End",
  };
  if (map[k]) return map[k];
  return k.startsWith("shift+") ? `Shift+${k.slice(6).toUpperCase()}` : k;
}
