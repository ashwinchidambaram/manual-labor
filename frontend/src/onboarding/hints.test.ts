import { describe, expect, it } from "vitest";
import { HOTKEYS } from "../hotkeys";
import { GLOSSARY } from "./glossary";
import { HINTS, SIGNAL_HINTS, type HintEntry } from "./hints";
import { STEPS } from "./StepNav";

// every source file, as text: the registry must cover every <Hint id="..."> in the app
const sources = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("U2 hint registry", () => {
  it("every hint has a term and text, and its hotkey exists", () => {
    for (const [id, h] of Object.entries(HINTS) as [string, HintEntry][]) {
      expect(h.term.trim(), id).not.toBe("");
      expect(h.text.trim(), id).not.toBe("");
      if (h.hotkey) expect(HOTKEYS[h.hotkey], id).toBeDefined();
      expect(h.text, id).not.toMatch(/—|!/);
    }
    for (const t of Object.values(SIGNAL_HINTS)) expect(t.trim()).not.toBe("");
  });
  it("every Hint used in the source is registered", () => {
    const used = new Set<string>();
    for (const src of Object.values(sources)) for (const m of src.matchAll(/<Hint\b[^>]*\bid="([A-Za-z0-9]+)"/g)) used.add(m[1]);
    for (const s of STEPS) used.add(s.hint);
    expect(used.size).toBeGreaterThan(15);
    for (const id of used) expect(id in HINTS, id).toBe(true);
  });
  it("the glossary lists every hint and every signal", () => {
    expect(GLOSSARY.length).toBe(Object.keys(HINTS).length + Object.keys(SIGNAL_HINTS).length);
    for (const id of Object.keys(HINTS)) expect(GLOSSARY.some((g) => g.id === id), id).toBe(true);
  });
});
