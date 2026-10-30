// Getting-started content (design 12 section 2.1). Pure data: the guide panel, the Help dialog's Guide tab and
// docs/USER_GUIDE.md all render from here. Keys are never written literally: `{hotkeyId}` tokens render the key
// from HOTKEYS, so a rebinding cannot leave stale copy behind.
import { HOTKEYS, displayKey, type HotkeyId } from "../hotkeys";

/** Bump when the content changes materially: the guide is then shown once more. Mirrors the server's value. */
export const GUIDE_VERSION = 1;

export type StepId = "scope" | "verify" | "agent" | "export";

export interface GuideStep {
  id: StepId;
  route: string;
  title: string;
  what: string;
  do: string[];
  /** every hotkey the copy refers to, as `{id}` tokens */
  keys: HotkeyId[];
  trust: string[];
}

export const GUIDE_STEPS: GuideStep[] = [
  {
    id: "scope",
    route: "/scope",
    title: "Choose what goes into your knowledge base",
    what:
      "Every block you select becomes text in an article. Suggested topics and Document structure are two views of the same blocks: switching views never changes the selection, and each view shows how much of a group is selected.",
    do: [
      "Move through the list with {moveDown} and {moveUp}. {toggleRow} selects or clears a row; {selectAll} selects everything.",
      "{toggleView} switches views. Low cohesion means a topic mixes subjects: check it in Document structure.",
      "Unassigned holds the blocks no topic claimed. They are listed here, never dropped.",
      "Estimated review is how many selected blocks will need a person. {confirm} confirms: scoring starts and Verify opens at once.",
    ],
    keys: ["moveDown", "moveUp", "toggleRow", "selectAll", "toggleView", "confirm"],
    trust: [
      "Under each document a line adds up its blocks: parsed = headers and footers + blocks in topics + unassigned.",
      "Choosing topics never changes the text. It only decides which blocks are reviewed and exported.",
    ],
  },
  {
    id: "verify",
    route: "/verify",
    title: "Review what the checks could not clear",
    what:
      "The queue lists only the blocks the machine is unsure about, worst first, and each card says why. Blocks with numbers, units or part numbers are always queued: OCR mistakes in numbers are likely and a language model cannot see them.",
    do: [
      "{vApprove} approves. On a block with numbers it also records that you checked the numbers.",
      "{vEdit} edits and {vSaveEdit} saves. {vFlag} flags the block with a category. {vSkip} skips, {vBack} goes back.",
      "{vToggleDiff} shows every change cleanup made against the raw parse.",
      "The slider only shows auto-approved blocks for a second look. It never changes their status.",
      "Figures: {vFocusRail} focuses the figure rail. Attach a figure re-attaches, {vRailDetach} detaches, {vRailCrop} adjusts the crop.",
    ],
    keys: ["vApprove", "vEdit", "vSaveEdit", "vFlag", "vSkip", "vBack", "vToggleDiff", "vFocusRail", "vRailDetach", "vRailCrop"],
    trust: [
      "Checks on this block lists each deterministic check and its result. A check that has not run says so; it is never shown as passed.",
      "The status line adds up: in scope = to review + auto-approved + done + flagged.",
    ],
  },
  {
    id: "agent",
    route: "/agent",
    title: "Hand flagged blocks to a model",
    what:
      "Flags you raised can be handed to a model, one fresh call per item. Every proposal is re-checked by the same deterministic checks, and failed checks are shown, not hidden.",
    do: [
      "Run the agent pass for the open flags. You can keep reviewing while it runs.",
      "Accept, edit or reject each proposal. A rejected item goes back to the queue with what was tried.",
      "Calibration shows how often you edited blocks at each confidence level and suggests a threshold. It never changes the threshold for you.",
    ],
    keys: [],
    trust: ["A proposal's model rationale is shown next to the evidence it quotes; quotes not found in the source are struck through."],
  },
  {
    id: "export",
    route: "/export",
    title: "Export the reviewed knowledge base",
    what:
      "Export unlocks when no flag is open and nothing in scope is still waiting for review. While it is locked, the screen lists exactly what blocks it, with a link to each.",
    do: [
      "Resolve the listed blocks in Verify or on the Agent screen.",
      "Or export anyway: an override needs a reason, and every overridden block is listed in manifest.json.",
      "Download the zip and compare its SHA-256 with the one shown.",
    ],
    keys: [],
    trust: ["The export contains only text a person or the checks accepted, plus any blocks you overrode with a recorded reason."],
  },
];

export const GUARANTEES: { claim: string; how: string }[] = [
  {
    claim: "The same file gives the same result.",
    how: "Parsing, IDs, scoring, the faithfulness check and assembly are deterministic code.",
  },
  {
    claim: "Cleanup cannot rewrite your text.",
    how: "It may only join hyphenated lines, fix whitespace, remove headers and footers, normalise bullets and fix reading order. Any other change to characters or numbers fails the faithfulness check, and the block is queued with the diff.",
  },
  {
    claim: "Confidence comes from disagreement, not from a model's opinion of itself.",
    how: "Two parsers, the text layer against OCR, and a separate verifier are compared. No model rates its own output.",
  },
  {
    claim: "Every model output is validated before you see it.",
    how: "Proposals and cleanups go through the same deterministic checks as everything else.",
  },
  {
    claim: "Learning from your edits is visible.",
    how: "Each block shows which learned rules touched it (Why did this change?), and each rule can be disabled or reset.",
  },
  {
    claim: "Nothing is dropped silently.",
    how: "Counts reconcile on every screen, and every block ends up in an article or in the unassigned list.",
  },
];

/** The display form of a hotkey: its first key, with the Ctrl/Cmd prefix for modifier entries. */
export function keyLabel(id: HotkeyId): string {
  const h = HOTKEYS[id];
  return `${h.mod ? "Ctrl/Cmd+" : ""}${displayKey(h.keys[0])}`;
}

export type CopyPart = { text: string } | { key: HotkeyId };
const TOKEN = /\{([A-Za-z0-9]+)\}/g;

/** Split copy into text and hotkey parts; an unknown `{token}` stays literal text (the guide test rejects it). */
export function copyParts(s: string): CopyPart[] {
  const out: CopyPart[] = [];
  let last = 0;
  for (const m of s.matchAll(TOKEN)) {
    const id = m[1];
    if (!(id in HOTKEYS)) continue;
    if (m.index! > last) out.push({ text: s.slice(last, m.index) });
    out.push({ key: id as HotkeyId });
    last = m.index! + m[0].length;
  }
  if (last < s.length) out.push({ text: s.slice(last) });
  return out;
}

/** Copy with tokens replaced by `key`'s output (plain text for the markdown guide). */
export function copyText(s: string, key: (id: HotkeyId) => string = keyLabel): string {
  return copyParts(s)
    .map((p) => ("key" in p ? key(p.key) : p.text))
    .join("");
}

/** The step for a route; unknown routes fall back to the first step. */
export function stepForPath(path: string): number {
  const i = GUIDE_STEPS.findIndex((s) => path.startsWith(s.route));
  return i < 0 ? 0 : i;
}
