// Single hotkey map for the whole UI. Every keyboard binding lives here (design 08 section 4.1).
// Key names are `event.key` lower-cased; Space is "space"; Shift is only expressed as "shift+<letter>".

export type HotkeyScope =
  | "global"
  | "scope"
  | "tree"
  | "models"
  | "verify"
  | "verifyQueue"
  | "verifySource"
  | "verifyRail"
  | "verifyEdit"
  | "flagDialog"
  | "picker";

/** Screen scopes are active only while that screen is mounted; zone scopes also need focus inside `data-zone`. */
export const SCREEN_OF: Record<HotkeyScope, HotkeyScope | null> = {
  global: null,
  scope: "scope",
  tree: "scope",
  models: "scope",
  verify: "verify",
  verifyQueue: "verify",
  verifySource: "verify",
  verifyRail: "verify",
  verifyEdit: "verify",
  flagDialog: null,
  picker: null,
};
/** zone scope -> the `data-zone` value the focus must be inside */
export const ZONE_OF: Partial<Record<HotkeyScope, string>> = {
  tree: "tree",
  models: "models",
  verifyQueue: "queue",
  verifySource: "source",
  verifyRail: "rail",
  verifyEdit: "edit",
};
/** scopes of modal dialogs: while one is open (`[aria-modal][data-hotkey-scope]`) it shadows every other scope */
export const MODAL_SCOPES: ReadonlySet<HotkeyScope> = new Set<HotkeyScope>(["flagDialog", "picker"]);

export const SCOPE_TITLES: Record<HotkeyScope, string> = {
  global: "Everywhere",
  scope: "Scope screen",
  tree: "Inside the group list",
  models: "Model panel",
  verify: "Verify screen",
  verifyQueue: "Verify: queue",
  verifySource: "Verify: source pane",
  verifyRail: "Verify: figure rail",
  verifyEdit: "Verify: editing",
  flagDialog: "Flag dialog",
  picker: "Picker",
};

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
  /** fire while typing in an input, textarea or select */
  allowInInputs?: boolean;
  /** require Ctrl or Meta (other entries ignore modified keys) */
  mod?: boolean;
  /** Space/Enter on a focused button or link keep their native meaning */
  nativeButtons?: boolean;
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
  toggleRow: { keys: ["space"], scope: "tree", label: "Toggle the row (partial selects the rest)", nativeButtons: true },
  selectOnly: { keys: ["enter"], scope: "tree", label: "Select only this row", nativeButtons: true },
  selectWholeDoc: { keys: ["shift+a"], scope: "tree", label: "Select the whole document of this row" },
};

/**
 * Arrow keys handled inside a widget (native radio-group feel, list navigation). They are not global hotkeys, so
 * they are not in HOTKEYS; they are listed here so Help documents every key in the UI.
 */
export const LOCAL_KEYS: { widget: string; keys: string[]; label: string }[] = [
  { widget: "Sources list", keys: ["arrowdown", "arrowup"], label: "Move between sources" },
  {
    widget: "Radio groups (view, article split, model tier)",
    keys: ["arrowleft", "arrowright", "arrowup", "arrowdown"],
    label: "Move to and select the neighbouring option",
  },
];

/** Normalised key name of a keyboard event; "shift+x" only for letters. */
export function keyName(e: Pick<KeyboardEvent, "key" | "shiftKey">): string {
  if (e.key === " ") return "space";
  const k = e.key.toLowerCase();
  return e.shiftKey && /^[a-z]$/.test(k) ? `shift+${k}` : k;
}

export function matches(e: Pick<KeyboardEvent, "key" | "shiftKey">, id: HotkeyId): boolean {
  return HOTKEYS[id].keys.includes(keyName(e));
}

/** True when two entries could fire for the same key press, so they must not share a key. */
export function scopesOverlap(a: HotkeyScope, b: HotkeyScope): boolean {
  if (a === b) return true;
  const ma = MODAL_SCOPES.has(a);
  const mb = MODAL_SCOPES.has(b);
  if (ma || mb) return false; // a modal shadows everything else, including the globals
  if (a === "global" || b === "global") return true;
  const sa = SCREEN_OF[a];
  const sb = SCREEN_OF[b];
  if (sa !== sb) return false; // different screens are never mounted together
  return a === sa || b === sb; // a screen scope overlaps its zones; sibling zones do not overlap
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
