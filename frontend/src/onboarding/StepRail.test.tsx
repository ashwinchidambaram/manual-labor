import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { defaultNextStep } from "../shell/nextStep";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { welcomeCopy } from "./WelcomeBand";

const unseen = { seen: false, seen_at: null, version: 1 };
const rail = () => screen.findByRole("complementary", { name: "Getting started" });

describe("U6 step rail and welcome (design 13 sections 2.5.1-2.5.2, design 12 section 4)", () => {
  it("the rail is always there, outside every data-zone, never modal, and does not take focus on Scope", async () => {
    installFake();
    renderApp("/scope");
    const r = await rail();
    expect(r).toHaveAttribute("data-step", "scope");
    expect(within(r).getByTestId("next-step")).toHaveTextContent(/confirms: scoring starts and Verify opens/);
    await waitFor(() => expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull());
    expect(r.contains(document.activeElement)).toBe(false);
    expect(r.closest("[data-zone]")).toBeNull();
    expect(r).not.toHaveAttribute("aria-modal");
  });
  it("a first run shows the welcome on Scope; a seen project does not", async () => {
    installFake({ guide: unseen });
    renderApp("/scope");
    expect(await screen.findByTestId("welcome")).toHaveTextContent("Start with step 1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("stays hidden when the server says it was seen", async () => {
    installFake();
    renderApp("/scope");
    await screen.findByTestId("group-tree");
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("welcome")).toBeNull();
  });
  it("either welcome button PUTs seen=true; from inside, focus goes to the group list", async () => {
    const f = installFake({ guide: unseen });
    const { user } = renderApp("/scope");
    const start = await screen.findByTestId("welcome-start");
    start.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByTestId("welcome")).toBeNull());
    await waitFor(() => expect(f.guidePuts).toEqual([true]));
    expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull();
  });
  it("a mouse press on the rail's text never takes focus", async () => {
    installFake();
    const { user } = renderApp("/scope");
    const r = await rail();
    await waitFor(() => expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull());
    const before = document.activeElement;
    await user.click(within(r).getByTestId("next-step-text"));
    expect(document.activeElement).toBe(before);
  });
  it("follows the route", async () => {
    installFake();
    const { router } = renderApp("/scope");
    expect(await rail()).toHaveAttribute("data-step", "scope");
    await act(async () => {
      await router.navigate("/agent");
    });
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Getting started" })).toHaveAttribute("data-step", "agent"));
  });
  it("a mock project says so calmly, with where to set real models", async () => {
    installFake();
    renderApp("/export");
    const r = await rail();
    await waitFor(() => expect(within(r).getByRole("note")).toHaveTextContent("Demo models are on. Model output is placeholder text; real models are set in Scope, under Models."));
  });
});

describe("next-step and welcome copy says only what the counts say", () => {
  it("defaults per step from the export gate", () => {
    const gate = { unlocked: false, open_flags: 2, queued: 1, blockers: ["b"], overrides: [] };
    expect(defaultNextStep("agent", gate).text).toBe("Run the agent pass on 2 open flags. Every proposal is checked again before you decide.");
    expect(defaultNextStep("agent", { ...gate, open_flags: 0 }).text).toMatch(/^Nothing is flagged\./);
    expect(defaultNextStep("export", gate).text).toBe("1 block still waits for review. 2 open flags still block the export. Export unlocks when both are done.");
    expect(defaultNextStep("export", { ...gate, blockers: [], unlocked: true }).text).toMatch(/SHA-256/);
    expect(defaultNextStep("verify", gate).text).toBe("Check each block against its page. 1 block waits for you.");
  });
  it("welcome numbers are the server's, and the numeric sentence follows them", () => {
    const base = { manuals: 3, pages: 32, blocks: 364, figures: 20, everything: true, queued: 216, numericQueued: 207 };
    const c = welcomeCopy(base);
    expect(c.title).toBe("Welcome. Your 3 manuals are read and ready.");
    expect(c.body).toContain("found 364 blocks of text (paragraphs, lists and tables) and 20 figures");
    expect(c.steps[1]).toEqual({ title: "Check 216 blocks against the page", line: "207 of them contain numbers, which a person always checks." });
    expect(welcomeCopy({ ...base, everything: false }).body).toContain("Selected right now: 364 blocks of text and 20 figures.");
    expect(welcomeCopy({ ...base, manuals: 1 }).title).toBe("Welcome. Your manual is read and ready.");
    expect(welcomeCopy({ ...base, numericQueued: 216 }).steps[1].line).toBe("All of them contain numbers, which a person always checks.");
  });
});
