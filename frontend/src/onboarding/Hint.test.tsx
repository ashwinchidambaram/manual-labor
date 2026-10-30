import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import Hint from "./Hint";
import { HINTS } from "./hints";

function Harness() {
  return (
    <div>
      <button type="button">before</button>
      <Hint id="confirm">
        <button type="button" aria-describedby="own-note">
          Go
        </button>
      </Hint>
      <span id="own-note">note</span>
    </div>
  );
}

describe("U5 Hint", () => {
  it("shows on keyboard focus, outside the trigger, with aria-describedby only while open", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const go = screen.getByRole("button", { name: "Go" });
    expect(go.getAttribute("aria-describedby")).toBe("own-note");
    await user.tab();
    await user.tab();
    expect(go).toHaveFocus();
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent(HINTS.confirm.text);
    expect(tip).toHaveTextContent("g"); // the key from HOTKEYS
    expect(go.contains(tip)).toBe(false);
    expect(go).toHaveTextContent(/^Go$/);
    expect(go.getAttribute("aria-describedby")).toBe(`own-note ${tip.id}`);
    await user.tab();
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(go.getAttribute("aria-describedby")).toBe("own-note");
  });
  it("shows on hover after a delay and hides on leave", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const go = screen.getByRole("button", { name: "Go" });
    await user.hover(go);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await user.unhover(go);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("does not show when focus comes from a click", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Go" }));
    await user.unhover(screen.getByRole("button", { name: "Go" }));
    await new Promise((r) => setTimeout(r, 450));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("Esc with a tooltip open closes only the tooltip: the app's own Esc handlers do not see it, focus stays put", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const appEsc: string[] = [];
    const onDoc = (e: KeyboardEvent): void => {
      if (e.key === "Escape") appEsc.push("document");
    };
    document.addEventListener("keydown", onDoc);
    await user.tab();
    await user.tab();
    await screen.findByRole("tooltip");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    expect(appEsc).toEqual([]);
    expect(screen.getByRole("button", { name: "Go" })).toHaveFocus();
    // with no tooltip open, Esc reaches the app exactly as before, not prevented
    let prevented: boolean | null = null;
    const spy = (e: KeyboardEvent): void => {
      if (e.key === "Escape") prevented = e.defaultPrevented;
    };
    document.addEventListener("keydown", spy);
    await user.keyboard("{Escape}");
    expect(appEsc).toEqual(["document"]);
    expect(prevented).toBe(false);
    document.removeEventListener("keydown", onDoc);
    document.removeEventListener("keydown", spy);
  });
  it("a click on the trigger cancels a pending hover tooltip, so a later Esc belongs to whatever the click opened", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const go = screen.getByRole("button", { name: "Go" });
    await user.hover(go);
    await user.click(go);
    await new Promise((r) => setTimeout(r, 450));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("focus the app moves itself after Enter or Esc (a dialog returning focus) shows no tooltip", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("button", { name: "before" }).focus();
    await user.keyboard("{Enter}");
    screen.getByRole("button", { name: "Go" }).focus();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("an Esc the open tooltip swallows still counts as the last key: focus the app then moves shows no tooltip", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <Hint id="confirm">
          <button type="button">Go</button>
        </Hint>
        <Hint id="confirm">
          <button type="button">Other</button>
        </Hint>
      </div>,
    );
    await user.tab();
    await screen.findByRole("tooltip");
    await user.keyboard("{Escape}"); // stopped by the tooltip before any document listener
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    screen.getByRole("button", { name: "Other" }).focus(); // the app moves focus after that Esc
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
