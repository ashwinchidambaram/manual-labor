import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HOTKEYS, LOCAL_KEYS } from "../hotkeys";
import { GLOSSARY } from "../onboarding/glossary";
import { GUIDE_STEPS } from "../onboarding/guide";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { op } from "../test/verifyFake";
import { mountVerify } from "../verify/helpers.test-util";

const conflictBody = {
  detail: "This edit changes content",
  code: "edit_conflict",
  conflict: {
    violations: [{ kind: "numeric_mismatch", raw: "0.25", clean: "0.99", raw_start: 0, raw_end: 4, clean_start: 0, clean_end: 4 }],
    numeric_changes: ["0.25 → 0.99"],
    diff: [op("equal", true, "set ", "set "), op("replace", false, "0.25", "0.99")],
  },
};

describe("U8 Help", () => {
  it("opens on the Guide tab; Left/Right switch tabs; shortcuts and glossary are complete", async () => {
    installFake();
    const { user } = renderApp("/export");
    await screen.findByTestId("export-screen");
    await user.keyboard("?");
    const dlg = screen.getByRole("dialog", { name: "Help" });
    expect(within(dlg).getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true");
    expect(within(dlg).getByTestId("help-guide")).toBeVisible();
    for (const s of GUIDE_STEPS) expect(within(dlg).getByTestId("help-guide")).toHaveTextContent(s.title);
    expect(within(dlg).getByTestId("help-keys")).not.toBeVisible();
    within(dlg).getByRole("tab", { name: "Guide" }).focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(within(dlg).getByRole("tab", { name: "Keyboard shortcuts" })).toHaveFocus());
    expect(within(dlg).getByTestId("help-keys")).toBeVisible();
    expect(within(dlg).getAllByTestId("hotkey-row")).toHaveLength(Object.values(HOTKEYS).length);
    expect(within(dlg).getByTestId("help-keys")).toHaveTextContent(LOCAL_KEYS[LOCAL_KEYS.length - 1].label);
    await user.keyboard("{ArrowRight}");
    expect(within(dlg).getAllByTestId("glossary-entry")).toHaveLength(GLOSSARY.length);
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    await waitFor(() => expect(within(dlg).getByRole("tab", { name: "Guide" })).toHaveAttribute("aria-selected", "true"));
  });
  it("Tab stays inside the dialog, skipping hidden panels; Esc restores focus", async () => {
    installFake();
    const { user } = renderApp("/export");
    await screen.findByTestId("export-screen");
    const help = screen.getByRole("button", { name: "Help" });
    help.focus();
    await user.keyboard("{Enter}");
    const dlg = screen.getByRole("dialog", { name: "Help" });
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dlg.contains(document.activeElement)).toBe(true);
      expect(document.activeElement?.closest("[hidden]")).toBeNull();
    }
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(help).toHaveFocus();
  });
  it("each tab panel is a keyboard stop (so it can be scrolled), and the trap still cycles through it", async () => {
    installFake();
    const { user } = renderApp("/export");
    await screen.findByTestId("export-screen");
    await user.keyboard("?");
    const dlg = screen.getByRole("dialog", { name: "Help" });
    for (const [tab, id] of [["Guide", "help-guide"], ["Keyboard shortcuts", "help-keys"], ["Glossary", "help-glossary"]] as const) {
      await user.click(within(dlg).getByRole("tab", { name: tab }));
      const panel = within(dlg).getByTestId(id);
      expect(panel).toHaveAttribute("tabindex", "0");
      const close = within(dlg).getByRole("button", { name: "Close" });
      close.focus();
      const visited: Element[] = [];
      for (let i = 0; i < 8 && !visited.includes(document.activeElement!); i++) {
        visited.push(document.activeElement!);
        await user.tab();
      }
      expect(visited, tab).toContain(panel);
      expect(document.activeElement, `${tab}: Tab wraps back to Close`).toBe(close);
    }
  });
  it("Show the welcome again closes Help, opens Scope with the welcome, and takes no focus into it", async () => {
    const f = installFake();
    const { user } = renderApp("/export");
    await screen.findByTestId("export-screen");
    await user.click(screen.getByRole("button", { name: "Help" }));
    const help = screen.getByRole("dialog", { name: "Help" });
    expect(help).toHaveTextContent("The four steps are always on screen: on the left, or along the bottom in a narrow window.");
    await user.click(screen.getByRole("button", { name: "Show the welcome again" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(f.guidePuts).toEqual([false]));
    const w = await screen.findByTestId("welcome", undefined, { timeout: 5000 });
    expect(w.contains(document.activeElement)).toBe(false);
  });
  it("? while the edit conflict panel is open opens Help, and closing it restores focus to Confirm (F7)", async () => {
    const { r } = await mountVerify(3, (fk) => {
      fk.actionHook = (_a, n) => (n === 0 ? { status: 409, body: conflictBody } : null);
    });
    await r.user.keyboard("e");
    await r.user.keyboard(" 999");
    await r.user.keyboard("{Control>}{Enter}{/Control}");
    await screen.findByTestId("edit-conflict");
    const confirm = screen.getByRole("button", { name: "Confirm content change" });
    await waitFor(() => expect(confirm).toHaveFocus());
    await r.user.keyboard("?");
    expect(screen.getByRole("dialog", { name: "Help" })).toBeInTheDocument();
    await r.user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
    expect(confirm).toHaveFocus();
    expect(screen.getByTestId("edit-conflict")).toBeInTheDocument();
  });
});
