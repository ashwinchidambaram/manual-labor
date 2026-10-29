import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { bid } from "../test/fixtures";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";

const a = (p: number, n: number) => bid("alpha", p, n);
const row = (id: string) => document.querySelector<HTMLElement>(`[data-testid=row][data-group-id="${id}"]`)!;
const blocks = () => screen.getByTestId("sum-blocks");
const loaded = async (path = "/scope") => {
  const r = renderApp(path);
  await screen.findByTestId("group-tree");
  await screen.findByTestId("sum-blocks");
  return r;
};

describe("C2 ViewToggle", () => {
  it("is a radiogroup, switches with t and the radio, writes set_view and the URL", async () => {
    const f = installFake();
    const { user, router } = await loaded();
    const group = screen.getByRole("radiogroup", { name: "Grouping view" });
    expect(within(group).getByRole("radio", { name: "Suggested topics" })).toHaveAttribute("aria-checked", "true");
    await user.keyboard("t");
    expect(within(group).getByRole("radio", { name: "Document structure" })).toHaveAttribute("aria-checked", "true");
    expect(router.state.location.search).toBe("?view=structure");
    expect(screen.getByRole("tree", { name: "Document structure" })).toBeInTheDocument();
    await waitFor(() => expect(f.puts.map((p) => [p.op, p.view])).toEqual([["set_view", "structure"]]));
    await user.click(within(group).getByRole("radio", { name: "Suggested topics" }));
    expect(screen.getByRole("listbox", { name: "Suggested topics" })).toBeInTheDocument();
    expect(screen.getByTestId("live")).toHaveTextContent("Switched to Suggested topics view");
  });
  it("restores the server-persisted view when the URL has none", async () => {
    installFake({ view: "structure" });
    await loaded();
    expect(screen.getByRole("tree", { name: "Document structure" })).toBeInTheDocument();
  });
  it("keeps the selection when toggling", async () => {
    installFake({ ids: [a(1, 1), a(1, 2), a(2, 1)] });
    const { user } = await loaded();
    expect(blocks()).toHaveTextContent("3");
    await user.keyboard("t");
    expect(blocks()).toHaveTextContent("3");
    await user.keyboard("t");
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "checked");
  });
});

describe("C3 GroupTree structure", () => {
  it("has tree roles, levels, expansion and a mixed checkbox; subtree select sends subtree:true", async () => {
    const f = installFake({ ids: [a(2, 1)] });
    const { user } = await loaded("/scope?view=structure");
    const s1 = row("g-alpha-s001");
    expect(s1).toHaveAttribute("role", "treeitem");
    expect(s1).toHaveAttribute("aria-level", "1");
    expect(s1).toHaveAttribute("aria-expanded", "true");
    expect(row("g-alpha-s002")).toHaveAttribute("aria-level", "2");
    expect(row("g-alpha-s003")).not.toHaveAttribute("aria-expanded");
    expect(row("g-alpha-s002").style.paddingLeft).not.toBe(s1.style.paddingLeft);
    expect(within(s1).getByRole("checkbox")).toHaveAttribute("aria-checked", "mixed");
    expect(within(row("g-alpha-s002")).getByRole("checkbox")).toHaveAttribute("aria-checked", "mixed");
    expect(screen.getByRole("tree")).toHaveAttribute("aria-multiselectable", "true");
    await user.click(s1);
    await waitFor(() => expect(f.puts).toHaveLength(1));
    expect(f.puts[0]).toMatchObject({ op: "select_group", group_id: "g-alpha-s001", subtree: true });
    expect(within(row("g-alpha-s001")).getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
    await user.click(row("g-alpha-s001"));
    await waitFor(() => expect(f.puts).toHaveLength(2));
    expect(f.puts[1]).toMatchObject({ op: "deselect_group", subtree: true });
  });
  it("chevron collapses without toggling the selection", async () => {
    const f = installFake();
    const { user } = await loaded("/scope?view=structure");
    await user.click(within(row("g-alpha-s001")).getByRole("button", { name: "Collapse section" }));
    expect(row("g-alpha-s002")).toBeNull();
    expect(f.puts).toHaveLength(0);
  });
});

describe("C4 GroupTree topics", () => {
  it("lists Unassigned first, marks only low cohesion and shows the meta line", async () => {
    installFake();
    await loaded();
    const rows = screen.getAllByTestId("row");
    expect(rows[0]).toHaveAttribute("data-group-id", "g-alpha-t000");
    expect(rows[0]).toHaveTextContent("Unassigned blocks");
    expect(rows[0]).toHaveTextContent("Catch-all");
    expect(rows[0]).toHaveAttribute("role", "option");
    expect(screen.getAllByTestId("low-cohesion")).toHaveLength(1);
    expect(within(row("g-alpha-t002")).getByTestId("low-cohesion")).toHaveAccessibleName("Low cohesion 0.20");
    expect(within(row("g-beta-t001")).queryByTestId("low-cohesion")).toBeNull(); // 0.30 is not < 0.30
    expect(within(row("g-alpha-t002")).getByTestId("row-meta")).toHaveTextContent("pp. 2-4 · 3 blocks · 1 figure · 2 sections · cohesion 0.20");
    expect(within(row("g-alpha-t000")).queryByText(/cohesion/i)).toBeNull();
  });
  it("uses the per-document low_cohesion parameter", async () => {
    const docs = (await import("../test/fixtures")).makeDocs();
    docs[1].groups.params = { ...docs[1].groups.params, low_cohesion: 0.5 };
    installFake({ docs });
    await loaded();
    expect(screen.getAllByTestId("low-cohesion")).toHaveLength(2);
    expect(within(row("g-beta-t001")).getByTestId("low-cohesion")).toBeInTheDocument();
  });
});

describe("C5 coverage chips", () => {
  it("shows the fraction of each row, dims while a PUT is in flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const f = installFake({ ids: [a(1, 1), a(1, 2), a(2, 1)] });
    const { user } = await loaded();
    expect(within(row("g-alpha-t001")).getByTestId("coverage-chip")).toHaveTextContent("100% selected");
    expect(within(row("g-alpha-t002")).getByTestId("coverage-chip")).toHaveTextContent("0% selected");
    await user.keyboard("t");
    expect(within(row("g-alpha-s001")).getByTestId("coverage-chip")).toHaveTextContent("60% selected"); // 3 of 5
    expect(within(row("g-alpha-s002")).getByTestId("coverage-chip")).toHaveTextContent("33% selected");
    f.gate = gate;
    await user.click(row("g-alpha-s003"));
    await waitFor(() => expect(within(row("g-alpha-s003")).getByTestId("coverage-chip")).toHaveAttribute("data-stale", "true"));
    await act(async () => release());
    await waitFor(() => expect(within(row("g-alpha-s003")).getByTestId("coverage-chip")).toHaveAttribute("data-stale", "false"));
    expect(within(row("g-alpha-s003")).getByTestId("coverage-chip")).toHaveTextContent("100% selected");
  });
});

describe("C10 optimistic flow", () => {
  it("updates the summary before the PUT resolves, then reconciles", async () => {
    let release!: () => void;
    const f = installFake();
    f.gate = new Promise<void>((r) => (release = r));
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    expect(blocks()).toHaveTextContent("3"); // before the server answered
    expect(screen.getByTestId("sum-pages")).toHaveTextContent("2");
    expect(screen.getByTestId("sum-queued")).toHaveTextContent("2"); // a(1,2) is auto-approved
    await act(async () => release());
    await waitFor(() => expect(f.puts).toHaveLength(1));
    await waitFor(() => expect(within(row("g-alpha-t001")).getByTestId("coverage-chip")).toHaveAttribute("data-stale", "false"));
    expect(blocks()).toHaveTextContent("3");
    expect(screen.getByTestId("live")).toHaveTextContent("Selected: 3 blocks, 1 articles");
  });
  it("rolls back and toasts when the PUT is rejected", async () => {
    const f = installFake();
    f.failPut = { status: 500, detail: "database is locked" };
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    expect(blocks()).toHaveTextContent("3");
    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Selection not saved");
    expect(toast).toHaveTextContent("database is locked");
    await waitFor(() => expect(blocks()).toHaveTextContent("0"));
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "unchecked");
  });
  it("sends two quick toggles as two ordered PUTs with distinct request ids", async () => {
    const f = installFake();
    const { user } = await loaded();
    await user.click(row("g-alpha-t001"));
    await user.click(row("g-alpha-t002"));
    await waitFor(() => expect(f.puts).toHaveLength(2));
    expect(f.puts.map((p) => p.group_id)).toEqual(["g-alpha-t001", "g-alpha-t002"]);
    expect(new Set(f.puts.map((p) => p.request_id)).size).toBe(2);
    await waitFor(() => expect(f.ids).toHaveLength(6));
    expect(blocks()).toHaveTextContent("6");
  });
});

describe("C11 keyboard", () => {
  it("focuses the cursor row at load and uses a roving tabindex", async () => {
    installFake();
    const { user } = await loaded();
    await waitFor(() => expect(document.activeElement).toBe(row("g-alpha-t000")));
    expect(document.querySelectorAll("[data-testid=row][tabindex='0']")).toHaveLength(1);
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("g-alpha-t001"));
    expect(row("g-alpha-t000")).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(row("g-beta-t001"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("g-beta-t001"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("g-beta-t000"));
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(row("g-alpha-t000"));
  });
  it("Space toggles, Enter selects only, a/n select all/none", async () => {
    const f = installFake();
    const { user } = await loaded();
    await user.keyboard("j{Space}");
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "checked");
    await user.keyboard("j{Enter}");
    expect(row("g-alpha-t001")).toHaveAttribute("data-check", "unchecked");
    expect(row("g-alpha-t002")).toHaveAttribute("data-check", "checked");
    expect(blocks()).toHaveTextContent("3");
    await user.keyboard("a");
    expect(blocks()).toHaveTextContent("10");
    await waitFor(() => expect(f.ids).toHaveLength(10));
    await user.keyboard("n"); // asks first; the selection is untouched
    expect(blocks()).toHaveTextContent(/^10$/);
    await user.keyboard("n");
    expect(blocks()).toHaveTextContent(/^0$/);
    await waitFor(() => expect(f.ids).toHaveLength(0));
  });
  it("Shift+A selects the document of the cursor row", async () => {
    installFake();
    const { user } = await loaded();
    await user.keyboard("{Shift>}A{/Shift}");
    expect(blocks()).toHaveTextContent("7");
  });
  it("expands and collapses with l/h and the arrows", async () => {
    installFake();
    const { user } = await loaded("/scope?view=structure");
    await waitFor(() => expect(document.activeElement).toBe(row("g-alpha-s001")));
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(row("g-alpha-s002"));
    await user.keyboard("h");
    expect(document.activeElement).toBe(row("g-alpha-s001"));
    await user.keyboard("{ArrowLeft}");
    expect(row("g-alpha-s002")).toBeNull();
    expect(row("g-alpha-s001")).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("l");
    expect(row("g-alpha-s002")).not.toBeNull();
  });
  it("s cycles the split, m focuses the model panel and back, u the summary, o the sources", async () => {
    installFake();
    const { user } = await loaded();
    await user.keyboard("s");
    expect(screen.getByRole("radio", { name: /per document/ })).toHaveAttribute("aria-checked", "true");
    await user.keyboard("s");
    expect(screen.getByRole("radio", { name: /per topic/ })).toHaveAttribute("aria-checked", "true");
    await screen.findByRole("radiogroup", { name: "Model tier" });
    await user.keyboard("m");
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: /small/ }));
    await user.keyboard("m");
    expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull();
    await user.keyboard("u");
    expect(document.activeElement).toBe(screen.getByTestId("selection-summary"));
    await user.keyboard("o");
    expect(document.activeElement?.closest("[data-zone='sources']")).not.toBeNull();
    await user.keyboard("{Escape}");
    expect(document.activeElement?.closest("[data-zone='tree']")).not.toBeNull();
  });
  it("? opens a focus-trapped help dialog that Esc closes, restoring focus", async () => {
    installFake();
    const { user } = await loaded();
    await waitFor(() => expect(document.activeElement).toBe(row("g-alpha-t000")));
    await user.keyboard("?");
    const dlg = screen.getByRole("dialog", { name: "Keyboard help" });
    expect(dlg).toHaveTextContent("Toggle the row");
    expect(dlg).toHaveTextContent("Go to Scope");
    await user.keyboard("j"); // tree hotkeys are muted while the dialog is open
    expect(document.activeElement?.closest("[role='dialog']")).not.toBeNull();
    await user.tab();
    await user.tab();
    expect(dlg.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(row("g-alpha-t000"));
  });
  it("ignores hotkeys typed into form fields", async () => {
    installFake();
    const { user } = await loaded();
    const input = screen.getByTestId("upload-input");
    input.focus();
    await user.keyboard("a");
    expect(blocks()).toHaveTextContent("0");
  });
  it("number keys switch screens", async () => {
    installFake();
    const { user, router } = await loaded();
    await user.keyboard("2");
    expect(router.state.location.pathname).toBe("/verify");
    await user.keyboard("1");
    expect(router.state.location.pathname).toBe("/scope");
  });
});

describe("C12 states", () => {
  it("shows a busy skeleton first", async () => {
    installFake();
    renderApp();
    expect(screen.getByTestId("tree-loading")).toHaveAttribute("aria-busy", "true");
    await screen.findByTestId("group-tree");
  });
  it("shows an error alert with Retry that recovers", async () => {
    const f = installFake({ groupsError: true });
    const { user } = renderApp();
    const alert = await screen.findByTestId("tree-error");
    expect(alert).toHaveTextContent("internal: boom");
    f.groupsError = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("group-tree")).toBeInTheDocument();
  });
  it("shows the empty-project card", async () => {
    installFake({ docs: [], sources: [] });
    renderApp();
    expect(await screen.findByTestId("scope-empty")).toHaveTextContent("Add documents");
  });
  it("shows the topics-failed notice and the grouping placeholder", async () => {
    const docs = (await import("../test/fixtures")).makeDocs();
    docs[0].groups.topic_status = "failed";
    docs[0].groups.topic_error = "embedder down";
    const f = installFake({ docs });
    f.sources = [...f.sources, { ...f.sources[0], slug: "gamma", filename: "gamma.pdf" }];
    renderApp();
    expect(await screen.findByTestId("topics-failed")).toHaveTextContent("Topics unavailable: embedder down. Structure view still works.");
    expect(screen.getByTestId("grouping-placeholder")).toHaveTextContent("gamma.pdf: grouping...");
    expect(await screen.findByTestId("docs-processing")).toHaveTextContent("1 document still processing");
    expect(screen.getByTestId("confirm")).toBeDisabled();
  });
  it("tags a learned grouping snapshot", async () => {
    const docs = (await import("../test/fixtures")).makeDocs();
    docs[0].groups.learning_snapshot = "snap-3";
    installFake({ docs });
    renderApp();
    expect(await screen.findByText("learned grouping: snap-3")).toBeInTheDocument();
  });
});
