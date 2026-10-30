import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeProject } from "../test/fixtures";
import { renderApp } from "../test/render";
import { http, HttpResponse } from "msw";
import { installFake, server } from "../test/server";
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
  it("a failing PUT keeps the panel open and says so; Hide again hides it for this page load only", async () => {
    installFake({ guide: { seen: false, seen_at: null, version: 1 } });
    let puts = 0;
    server.use(http.put("*/api/ui/guide", () => (puts++, HttpResponse.json({ detail: "disk full", code: "internal" }, { status: 500 }))));
    const { user } = renderApp("/export");
    await waitFor(() => expect(panel()).not.toBeNull());
    await user.click(within(panel()!).getByTestId("guide-hide"));
    await waitFor(() => expect(puts).toBe(1));
    const alert = await within(panel()!).findByRole("alert");
    expect(alert).toHaveTextContent("Hiding the guide was not saved: disk full.");
    expect(alert).toHaveTextContent("Hide guide again to hide it until you reload");
    await user.click(within(panel()!).getByTestId("guide-hide"));
    await waitFor(() => expect(panel()).toBeNull());
  });
});
