import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeProject } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { storageKey } from "./useGuideState";

const panel = () => screen.queryByRole("complementary", { name: "Getting started" });
const KEY = storageKey(makeProject().root);

afterEach(() => {
  vi.restoreAllMocks();
  try {
    window.localStorage.clear();
  } catch {
    /* storage mocked away */
  }
});

describe("U7 useGuideState", () => {
  it("the server flag wins over localStorage", async () => {
    window.localStorage.setItem(KEY, "seen");
    installFake({ guide: { seen: false, seen_at: null, version: 1 } });
    renderApp("/export");
    await waitFor(() => expect(panel()).not.toBeNull());
  });
  it("a failing GET falls back to localStorage: unseen opens, Hide writes the key", async () => {
    const f = installFake({ guide: null });
    const { user } = renderApp("/export");
    await waitFor(() => expect(panel()).not.toBeNull());
    await user.click(within(panel()!).getByTestId("guide-hide"));
    await waitFor(() => expect(panel()).toBeNull());
    expect(window.localStorage.getItem(KEY)).toBe("seen");
    expect(f.guidePuts).toEqual([]);
  });
  it("a failing GET with the key stored keeps it hidden", async () => {
    window.localStorage.setItem(KEY, "seen");
    installFake({ guide: null });
    renderApp("/export");
    await screen.findByTestId("export-screen");
    await new Promise((r) => setTimeout(r, 50));
    expect(panel()).toBeNull();
  });
  it("storage that throws makes the flag session-only", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    installFake({ guide: null });
    const { user } = renderApp("/export");
    await waitFor(() => expect(panel()).not.toBeNull());
    await user.click(within(panel()!).getByTestId("guide-hide"));
    await waitFor(() => expect(panel()).toBeNull());
  });
});
