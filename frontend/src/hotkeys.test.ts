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
        if (ia >= ib || !scopesOverlap(a.scope, b.scope)) continue;
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
