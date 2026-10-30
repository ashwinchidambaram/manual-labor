import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";

const unseen = { seen: false, seen_at: null, version: 1 };
const panel = () => screen.findByRole("complementary", { name: "Getting started" });

describe("U6 GuidePanel", () => {
  it("auto-opens on a first run without moving focus (the tree keeps it on Scope)", async () => {
    installFake({ guide: unseen });
    renderApp("/scope");
    const p = await panel();
    expect(within(p).getByTestId("guide-title")).toHaveTextContent("Choose what goes into your knowledge base");
    await waitFor(() => expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull());
    expect(p.contains(document.activeElement)).toBe(false);
    expect(p.closest("[data-zone]")).toBeNull();
    expect(p).not.toHaveAttribute("aria-modal");
  });
  it("auto-open on a screen without autofocus leaves focus on the body", async () => {
    installFake({ guide: unseen });
    renderApp("/export");
    await panel();
    expect(document.activeElement).toBe(document.body);
  });
  it("a mock project shows the mock-models mode as a mode, with where to set real models", async () => {
    installFake({ guide: unseen });
    renderApp("/export");
    const p = await panel();
    expect(within(p).getByRole("note")).toHaveTextContent("Mock models are on: model output is placeholder text; real models are set in Scope → Models.");
  });
  it("stays hidden when the server says it was seen", async () => {
    installFake();
    renderApp("/scope");
    await screen.findByTestId("group-tree");
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("complementary", { name: "Getting started" })).toBeNull();
  });
  it("Hide PUTs seen=true; hiding from inside moves focus to the Help button", async () => {
    const f = installFake({ guide: unseen });
    const { user } = renderApp("/export");
    const p = await panel();
    within(p).getByTestId("guide-hide").focus();
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("complementary", { name: "Getting started" })).toBeNull();
    await waitFor(() => expect(f.guidePuts).toEqual([true]));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Help" }));
  });
  it("a mouse click on the guide never takes focus", async () => {
    installFake({ guide: unseen });
    const { user } = renderApp("/scope");
    const p = await panel();
    await waitFor(() => expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull());
    const before = document.activeElement;
    await user.click(within(p).getByTestId("guide-next"));
    expect(p).toHaveAttribute("data-step", "verify");
    expect(document.activeElement).toBe(before);
  });
  it("Next and Previous page through the steps; Done on the last one hides it", async () => {
    const f = installFake({ guide: unseen });
    const { user } = renderApp("/export");
    const p = await panel();
    expect(within(p).getByTestId("guide-progress")).toHaveTextContent("Step 4 of 4");
    expect(within(p).getByTestId("guide-next")).toHaveTextContent("Done");
    await user.click(within(p).getByRole("button", { name: "Previous" }));
    expect(p).toHaveAttribute("data-step", "agent");
    await user.click(within(p).getByTestId("guide-next"));
    await user.click(within(p).getByTestId("guide-next"));
    await waitFor(() => expect(f.guidePuts).toEqual([true]));
  });
  it("follows the route: arriving on /verify shows the Verify card", async () => {
    installFake({ guide: unseen });
    const { router } = renderApp("/scope");
    const p = await panel();
    expect(p).toHaveAttribute("data-step", "scope");
    await act(async () => {
      await router.navigate("/verify");
    });
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Getting started" })).toHaveAttribute("data-step", "verify"));
  });
  it("notes mock models", async () => {
    installFake({ guide: unseen });
    renderApp("/export");
    expect(await panel()).toHaveTextContent("Mock models");
  });
});
