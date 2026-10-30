// The Help glossary and the USER_GUIDE glossary: every hint plus every scoring signal, in registry order.
import { label } from "../verify/labels";
import { HINTS, SIGNAL_HINTS, type HintEntry, type HintId } from "./hints";

export interface GlossaryEntry {
  id: string;
  term: string;
  text: string;
  hotkey?: HintEntry["hotkey"];
}

export const GLOSSARY: GlossaryEntry[] = [
  ...(Object.keys(HINTS) as HintId[]).map((id) => {
    const h: HintEntry = HINTS[id];
    return { id, term: h.term, text: h.text, hotkey: h.hotkey };
  }),
  ...Object.entries(SIGNAL_HINTS).map(([name, text]) => ({ id: `signal:${name}`, term: `Signal: ${label(name)}`, text })),
];
