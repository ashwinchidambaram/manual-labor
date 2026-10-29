import { describe, expect, it } from "vitest";
import { HOTKEYS, keyName, matches, scopesOverlap, type HotkeyId } from "./hotkeys";

describe("U1 HOTKEYS map", () => {
  const entries = Object.entries(HOTKEYS) as [HotkeyId, (typeof HOTKEYS)[HotkeyId]][];
  it("has a label and at least one key for every entry", () => {
    for (const [id, h] of entries) {
      expect(h.label, id).toBeTruthy();
      expect(h.keys.length, id).toBeGreaterThan(0);
      for (const k of h.keys) expect(k, id).toBe(k.toLowerCase());
    }
  });
  it("has no key collisions between overlapping scopes", () => {
    for (const [ia, a] of entries)
      for (const [ib, b] of entries) {
        if (ia >= ib || !scopesOverlap(a.scope, b.scope) || !!a.mod !== !!b.mod) continue;
        const shared = a.keys.filter((k) => b.keys.includes(k));
        expect(shared, `${ia} vs ${ib}`).toEqual([]);
      }
  });
  it("normalises key names", () => {
    expect(keyName({ key: " ", shiftKey: false })).toBe("space");
    expect(keyName({ key: "A", shiftKey: true })).toBe("shift+a");
    expect(keyName({ key: "?", shiftKey: true })).toBe("?");
    expect(matches({ key: "ArrowDown", shiftKey: false }, "moveDown")).toBe(true);
    expect(matches({ key: "a", shiftKey: false }, "selectWholeDoc")).toBe(false);
  });
});

describe("U2 scope overlap across screens and zones", () => {
  it("per-screen scopes never collide with another screen's", () => {
    expect(scopesOverlap("scope", "verify")).toBe(false);
    expect(scopesOverlap("tree", "verify")).toBe(false);
    expect(scopesOverlap("scope", "verifyQueue")).toBe(false);
    expect(scopesOverlap("models", "verifyRail")).toBe(false);
  });
  it("a zone overlaps its own screen scope, not a sibling zone", () => {
    expect(scopesOverlap("tree", "scope")).toBe(true);
    expect(scopesOverlap("verifyQueue", "verify")).toBe(true);
    expect(scopesOverlap("tree", "models")).toBe(false);
    expect(scopesOverlap("verifyQueue", "verifyRail")).toBe(false);
  });
  it("global overlaps every non-modal scope; a modal shadows globals so may reuse their keys", () => {
    expect(scopesOverlap("global", "verify")).toBe(true);
    expect(scopesOverlap("global", "tree")).toBe(true);
    expect(scopesOverlap("global", "flagDialog")).toBe(false);
    expect(scopesOverlap("picker", "flagDialog")).toBe(false);
    expect(scopesOverlap("flagDialog", "flagDialog")).toBe(true);
  });
});

describe("VU5 verify keys", () => {
  const entries = Object.entries(HOTKEYS) as [HotkeyId, (typeof HOTKEYS)[HotkeyId]][];
  it("only Escape and Mod+Enter work inside inputs", () => {
    for (const [id, h] of entries)
      if (h.allowInInputs) expect(h.keys[0] === "escape" || (h.mod && h.keys[0] === "enter"), id).toBe(true);
  });
  it("flag dialog digits shadow the global screen keys without colliding in other scopes", () => {
    expect(HOTKEYS.vFlagCat1.keys).toEqual(HOTKEYS.goScope.keys);
    expect(scopesOverlap("flagDialog", "global")).toBe(false);
  });
  it("covers every key of the design table (a e f j k t s g / [ ] z, arrows, x, c)", () => {
    const all = new Set(entries.flatMap(([, h]) => (h.scope.startsWith("verify") || h.scope === "flagDialog" ? h.keys : [])));
    for (const k of ["a", "e", "f", "j", "k", "t", "s", "g", "/", "[", "]", "z", "escape", "x", "c", "arrowdown", "home", "end", "enter", "1", "5"])
      expect(all.has(k), k).toBe(true);
  });
});
