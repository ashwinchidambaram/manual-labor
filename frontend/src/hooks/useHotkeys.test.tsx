import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HOTKEYS, type HotkeyId } from "../hotkeys";
import { useHotkeys, type HotkeyHandlers } from "./useHotkeys";

// Entries a later screen will add; registered here only for the test.
const extra = {
  tInput: { keys: ["enter"], scope: "verifyEdit", label: "t", allowInInputs: true },
  tMod: { keys: ["enter"], scope: "verifyEdit", label: "t", mod: true, allowInInputs: true },
  tPlain: { keys: ["x"], scope: "verify", label: "t" },
  tQueue: { keys: ["arrowdown"], scope: "verifyQueue", label: "t" },
  tModal: { keys: ["1"], scope: "flagDialog", label: "t" },
  tBtn: { keys: ["space"], scope: "verify", label: "t", nativeButtons: true },
} as const;
const reg = HOTKEYS as unknown as Record<string, unknown>;
Object.assign(reg, extra);

function Host({ h, children }: { h: Record<string, () => void>; children?: React.ReactNode }) {
  useHotkeys(h as unknown as HotkeyHandlers);
  return <div>{children}</div>;
}
const id = (s: string) => s as HotkeyId;

describe("useHotkeys configurable rules", () => {
  it("allowInInputs entries fire inside inputs, others do not", () => {
    const a = vi.fn();
    const b = vi.fn();
    const { getByTestId } = render(
      <Host h={{ [id("tInput")]: a, [id("tPlain")]: b }}>
        <div data-zone="edit">
          <input data-testid="in" />
        </div>
      </Host>,
    );
    fireEvent.keyDown(getByTestId("in"), { key: "Enter" });
    fireEvent.keyDown(getByTestId("in"), { key: "x" });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).not.toHaveBeenCalled();
  });
  it("mod entries need Ctrl or Meta and plain entries ignore modified keys", () => {
    const m = vi.fn();
    const p = vi.fn();
    const { getByTestId } = render(
      <Host h={{ [id("tMod")]: m, [id("tPlain")]: p }}>
        <div data-zone="edit" data-testid="z" />
      </Host>,
    );
    const container = getByTestId("z");
    fireEvent.keyDown(container, { key: "Enter" });
    expect(m).not.toHaveBeenCalled();
    fireEvent.keyDown(container, { key: "Enter", metaKey: true });
    fireEvent.keyDown(container, { key: "Enter", ctrlKey: true });
    expect(m).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(container, { key: "x", ctrlKey: true });
    expect(p).not.toHaveBeenCalled();
  });
  it("zone scopes come from data-zone", () => {
    const q = vi.fn();
    const { getByTestId } = render(
      <Host h={{ [id("tQueue")]: q }}>
        <div data-zone="queue" data-testid="q" />
        <div data-zone="rail" data-testid="r" />
      </Host>,
    );
    fireEvent.keyDown(getByTestId("r"), { key: "ArrowDown" });
    expect(q).not.toHaveBeenCalled();
    fireEvent.keyDown(getByTestId("q"), { key: "ArrowDown" });
    expect(q).toHaveBeenCalledTimes(1);
  });
  it("an open modal with data-hotkey-scope shadows everything but its own scope", () => {
    const g = vi.fn();
    const m = vi.fn();
    const p = vi.fn();
    const { container } = render(
      <Host h={{ goScope: g, [id("tModal")]: m, [id("tPlain")]: p }}>
        <div role="dialog" aria-modal="true" data-hotkey-scope="flagDialog" />
      </Host>,
    );
    fireEvent.keyDown(container, { key: "1" });
    expect(m).toHaveBeenCalledTimes(1); // "1" is the modal's, not goScope's
    expect(g).not.toHaveBeenCalled();
    fireEvent.keyDown(container, { key: "x" });
    expect(p).not.toHaveBeenCalled();
  });
  it("nativeButtons entries keep their native meaning on buttons", () => {
    const s = vi.fn();
    const { getByTestId } = render(
      <Host h={{ [id("tBtn")]: s }}>
        <button data-testid="b" />
      </Host>,
    );
    fireEvent.keyDown(getByTestId("b"), { key: " " });
    expect(s).not.toHaveBeenCalled();
  });
});
