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
  it("review M13 P2-17: below the wide breakpoint the header labels model output too (the rail footer is hidden there)", async () => {
    installFake();
    renderApp("/export");
    const note = await screen.findByTestId("demo-note");
    expect(note).toHaveAttribute("role", "note");
    expect(note).toHaveTextContent("Demo models are on: model output is placeholder text");
    // shown at every width below `wide`; the rail's own note takes over from `wide` up
    expect(note.className).toContain("wide:hidden");
    expect(note.className).not.toMatch(/(^|\s)hidden(\s|$)/);
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
  it("the export step's every branch says only what the gate says", () => {
    const gate = { unlocked: false, open_flags: 1, queued: 0, blockers: ["b"], overrides: [] };
    expect(defaultNextStep("export", undefined).text).toBe("Export the reviewed knowledge base.");
    expect(defaultNextStep("export", gate).text).toBe("1 open flag still blocks the export. Export unlocks after that.");
    expect(defaultNextStep("export", { ...gate, open_flags: 0, queued: 3 }).text).toBe("3 blocks still wait for review. Export unlocks after that.");
    expect(defaultNextStep("export", { ...gate, open_flags: 0, queued: 0, blockers: [], unlocked: false }).text).toMatch(/SHA-256/);
  });
  const base = {
    manuals: 3,
    ready: 3,
    names: ["clean.pdf", "scanned.pdf", "manual.docx"],
    pages: 32,
    blocks: 364,
    figures: 20,
    types: { paragraph: 270, list: 11, heading: 44, caption: 19, figure: 20 },
    everything: true,
    queued: 216,
    numericQueued: 207,
  };
  it("welcome numbers are the server's, and the numeric sentence follows them", () => {
    const c = welcomeCopy(base);
    expect(c.title).toBe("Welcome. Your 3 manuals are read and ready.");
    expect(c.steps[1]).toEqual({ title: "Check 216 blocks against the page", line: "207 of them contain numbers, which a person always checks." });
    expect(welcomeCopy({ ...base, manuals: 1, ready: 1, names: ["clean.pdf"] }).title).toBe("Welcome. Your manual is read and ready.");
    expect(welcomeCopy({ ...base, numericQueued: 216 }).steps[1].line).toBe("All of them contain numbers, which a person always checks.");
    expect(welcomeCopy({ ...base, numericQueued: 0 }).steps[1].line).toBe("None of them contain numbers; each scored under the auto-approve line.");
    expect(welcomeCopy({ ...base, queued: 0, numericQueued: 0 }).steps[1].line).toBe("Nothing needs a person yet.");
  });
  it("the block count is broken down by the real block types and adds up; figures are not counted twice", () => {
    const c = welcomeCopy(base);
    expect(c.body).toContain("We read 32 pages and found 364 blocks: 270 paragraphs, 11 lists, 44 headings, 19 captions and 20 figures.");
    expect(c.body).not.toMatch(/blocks of text/);
    expect(welcomeCopy({ ...base, everything: false }).body).toContain("Selected right now: 364 blocks: 270 paragraphs");
  });
  it("without a breakdown that adds up, it says the total and how many are figures", () => {
    expect(welcomeCopy({ ...base, types: null }).body).toContain("found 364 blocks, 20 of them figures.");
    expect(welcomeCopy({ ...base, types: { paragraph: 1 } }).body).toContain("found 364 blocks, 20 of them figures.");
    expect(welcomeCopy({ ...base, types: null, figures: 0 }).body).toContain("found 364 blocks.");
  });
  it("counts only the manuals that are ready, and names every manual", () => {
    expect(welcomeCopy({ ...base, ready: 2 }).title).toBe("Welcome. 2 of your 3 manuals are ready; one is still being read.");
    expect(welcomeCopy({ ...base, ready: 1 }).title).toBe("Welcome. 1 of your 3 manuals is ready; 2 are still being read.");
    expect(welcomeCopy(base).manuals).toBe("clean.pdf, scanned.pdf and manual.docx");
  });
});
