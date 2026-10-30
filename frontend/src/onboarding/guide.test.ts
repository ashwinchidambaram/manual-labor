import { describe, expect, it } from "vitest";
import { HOTKEYS, type HotkeyId } from "../hotkeys";
import { CLEANUP_ALLOWED, GUARANTEES, GUIDE_STEPS, copyParts, copyText, keyLabel, keycap, stepForPath } from "./guide";

const allCopy = (): string[] => GUIDE_STEPS.flatMap((s) => [s.title, s.what, ...s.do, ...s.trust]).concat(GUARANTEES.flatMap((g) => [g.claim, g.how]));

describe("U1 guide content", () => {
  it("every step key exists in HOTKEYS, and every {token} in the copy is a declared key", () => {
    for (const s of GUIDE_STEPS) {
      for (const k of s.keys) expect(HOTKEYS[k], `${s.id}: ${k}`).toBeDefined();
      const used = new Set(
        [s.what, ...s.do, ...s.trust].flatMap((t) => [...t.matchAll(/\{([A-Za-z0-9]+)\}/g)].map((m) => m[1])),
      );
      for (const u of used) {
        expect(u in HOTKEYS, `${s.id}: unknown token {${u}}`).toBe(true);
        expect(s.keys, `${s.id}: {${u}} not listed in keys`).toContain(u as HotkeyId);
      }
    }
  });
  it("steps are in route order, one per screen", () => {
    expect(GUIDE_STEPS.map((s) => s.route)).toEqual(["/scope", "/verify", "/agent", "/export"]);
    expect(stepForPath("/verify")).toBe(1);
    expect(stepForPath("/nope")).toBe(0);
  });
  it("copy never writes a key literally: no backticked or quoted single characters, no 'press x'", () => {
    for (const t of allCopy()) {
      expect(t, t).not.toMatch(/`[^`]{1,3}`/);
      expect(t, t).not.toMatch(/["'][a-z?/[\]]["']/i);
      expect(t, t).not.toMatch(/\b(press|key)\s+[a-z?/]\b/i);
    }
  });
  it("copy has no em dashes and no exclamation marks", () => {
    for (const t of allCopy()) {
      expect(t, t).not.toMatch(/—|--/);
      expect(t, t).not.toContain("!");
    }
  });
  it("tokens render from HOTKEYS, with the modifier prefix for Mod entries", () => {
    expect(keyLabel("vApprove")).toBe(HOTKEYS.vApprove.keys[0].toUpperCase());
    expect(keyLabel("vSaveEdit")).toBe("Ctrl/Cmd+Enter");
    expect(copyParts("{vApprove} approves")).toEqual([{ key: "vApprove" }, { text: " approves" }]);
    expect(copyText("{vEdit} edits")).toBe("E edits");
  });
  it("keys render as keycaps: a single letter is upper case, named keys keep their names", () => {
    expect(keycap("a")).toBe("A");
    expect(keycap("?")).toBe("?");
    expect(keycap("arrowdown")).toBe("Down");
    expect(keycap("shift+g")).toBe("Shift+G");
  });
  it("copy makes no claim the code does not keep (review M12 #5, #8)", () => {
    const text = allCopy().join("\n");
    expect(text).not.toMatch(/same file gives the same result/i);
    expect(text).not.toMatch(/reconcile on every screen/i);
    expect(text).not.toMatch(/goes back to the (Verify )?queue/i);
    expect(text).toMatch(/optional verifier|verifier model when one is configured/);
    expect(text).toMatch(/Figure descriptions are only checked against their schema/);
    for (const t of ["whitespace", "hyphenated", "headers and footers", "reading order", "ligatures", "table layout", "bullets"]) expect(text).toContain(t);
    expect(text).toMatch(/chosen between text layer and OCR is recorded, not failed/);
    expect(text).toMatch(/leaves its flag open/);
  });
  it("reading order is accepted only when another reader attests it, never on layout alone (faithfulness.py, design 03 4.5)", () => {
    expect(CLEANUP_ALLOWED).toContain("fix reading order only where the other parser or OCR read the block in the cleaned order");
    expect(CLEANUP_ALLOWED).toContain("page layout alone is not evidence");
    expect(CLEANUP_ALLOWED).not.toMatch(/where the layout gives evidence/);
  });
});
