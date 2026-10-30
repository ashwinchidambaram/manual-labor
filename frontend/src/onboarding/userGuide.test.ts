import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { HOTKEYS } from "../hotkeys";
import { USER_GUIDE_HEADER, renderUserGuide } from "./userGuide";

const committed = (): string => readFileSync(resolve(__dirname, "../../../docs/USER_GUIDE.md"), "utf8");

describe("U3 docs/USER_GUIDE.md", () => {
  it("equals the generated guide (run `npm run gen-guide` after changing guide.ts, hints.ts or hotkeys.ts)", () => {
    expect(committed()).toBe(renderUserGuide());
  });
  it("has the generated header and one shortcut row per HOTKEYS entry", () => {
    const md = renderUserGuide();
    expect(md).toContain(USER_GUIDE_HEADER);
    const shortcuts = md.slice(md.indexOf("## Keyboard shortcuts"), md.indexOf("### Inside a widget"));
    const rows = shortcuts.split("\n").filter((l) => l.startsWith("| ") && !l.startsWith("| Keys"));
    expect(rows).toHaveLength(Object.values(HOTKEYS).length);
  });
  it("every key in the prose comes from HOTKEYS, including the Help key in Reset the guide", () => {
    const h = HOTKEYS.help as { keys: string[] };
    const saved = h.keys;
    h.keys = ["f1"];
    try {
      const md = renderUserGuide();
      const reset = md.slice(md.indexOf("## Reset the guide"));
      expect(reset).toContain("open Help (`f1`)");
      expect(reset).not.toContain("`?`");
    } finally {
      h.keys = saved;
    }
  });
});
