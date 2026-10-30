import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeProject } from "../test/fixtures";
import { renderApp } from "../test/render";
import { http, HttpResponse } from "msw";
import { installFake, server } from "../test/server";
import { storageKey } from "./useGuideState";

// The getting-started flag now decides the first-run welcome on Scope (design 13 section 2.5.2).
const welcome = () => screen.queryByTestId("welcome");
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
    renderApp("/scope");
    await waitFor(() => expect(welcome()).not.toBeNull());
  });
  it("a failing GET falls back to localStorage: unseen shows the welcome, dismissing writes the key", async () => {
    const f = installFake({ guide: null });
    const { user } = renderApp("/scope");
    await waitFor(() => expect(welcome()).not.toBeNull());
    await user.click(screen.getByTestId("welcome-dismiss"));
    await waitFor(() => expect(welcome()).toBeNull());
    expect(window.localStorage.getItem(KEY)).toBe("seen");
    expect(f.guidePuts).toEqual([]);
  });
  it("a failing GET with the key stored keeps it hidden", async () => {
    window.localStorage.setItem(KEY, "seen");
    installFake({ guide: null });
    renderApp("/scope");
    await screen.findByTestId("group-tree");
    await new Promise((r) => setTimeout(r, 50));
    expect(welcome()).toBeNull();
  });
  it("storage that throws makes the flag session-only", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    installFake({ guide: null });
    const { user } = renderApp("/scope");
    await waitFor(() => expect(welcome()).not.toBeNull());
    await user.click(screen.getByTestId("welcome-dismiss"));
    await waitFor(() => expect(welcome()).toBeNull());
  });
  it("a failing PUT keeps the welcome and says so; dismissing again hides it for this page load only", async () => {
    installFake({ guide: { seen: false, seen_at: null, version: 1 } });
    let puts = 0;
    server.use(http.put("*/api/ui/guide", () => (puts++, HttpResponse.json({ detail: "disk full", code: "internal" }, { status: 500 }))));
    const { user } = renderApp("/scope");
    await waitFor(() => expect(welcome()).not.toBeNull());
    await user.click(screen.getByTestId("welcome-dismiss"));
    await waitFor(() => expect(puts).toBe(1));
    const alert = await screen.findByText(/Hiding the welcome was not saved: disk full\./);
    expect(alert).toHaveTextContent("Dismiss it again to hide it until you reload");
    expect(welcome()).not.toBeNull();
    await user.click(screen.getByTestId("welcome-dismiss"));
    await waitFor(() => expect(welcome()).toBeNull());
  });
});
