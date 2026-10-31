// VC4 extracted pane, VC5 learning chip, VC6 rail and picker, VC7 flag dialog.
import { screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { http, HttpResponse, delay } from "msw";
import { server } from "../test/server";
import { describe, expect, it } from "vitest";
import type { DocFigure } from "../api/schema";
import { makeJob } from "../test/fixtures";
import { makeBlockDetail, makeQueueItem, makeRailItem, makeRecord, op, vid } from "../test/verifyFake";
import { card, cardFocused, mountVerify } from "./helpers.test-util";

const conflictBody = {
  detail: "This edit changes content",
  code: "edit_conflict",
  conflict: {
    violations: [{ kind: "numeric_mismatch", raw: "0.25", clean: "0.99", raw_start: 0, raw_end: 4, clean_start: 0, clean_end: 4 }],
    numeric_changes: ["0.25 → 0.99"],
    diff: [op("equal", true, "set ", "set "), op("replace", false, "0.25", "0.99")],
  },
};
const ctrlEnter = "{Control>}{Enter}{/Control}";

describe("VC4 ExtractedPane", () => {
  it("toggles between text and the diff with t and the buttons", async () => {
    const { r } = await mountVerify(2, (f) => {
      f.details[vid(1)] = makeBlockDetail(f.items[0], {}, {
        raw_text: "lubri-\ncation",
        clean_text: "lubrication",
        faithfulness: { passed: true, alignment_ratio: 1, violations: [], numeric_variants: [], diff: [op("equal", true, "lubri", "lubri"), op("delete", true, "-\n", ""), op("equal", true, "cation", "cation")] },
      });
    });
    expect(await screen.findByTestId("block-text")).toHaveTextContent("lubrication");
    await r.user.keyboard("t");
    const dv = await screen.findByTestId("diff-view");
    expect(within(dv).getByText("-↵")).toHaveAttribute("data-seg", "del-ok");
    expect(screen.getByTestId("view-diff")).toHaveAttribute("aria-pressed", "true");
    await r.user.click(screen.getByTestId("view-text"));
    expect(screen.queryByTestId("diff-view")).toBeNull();
  });

  it("M7 diff spans carry text alternatives for screen readers: 'removed: ...' and 'inserted: ...'", async () => {
    const { r } = await mountVerify(2, (f) => {
      f.details[vid(1)] = makeBlockDetail(f.items[0], {}, {
        raw_text: "set 0.25 mm",
        clean_text: "set 0.99 mm",
        faithfulness: { passed: false, alignment_ratio: 0.9, violations: [], numeric_variants: [], diff: [op("equal", true, "set ", "set "), op("replace", false, "0.25", "0.99"), op("equal", true, " mm", " mm")] },
      });
    });
    await screen.findByTestId("block-text");
    await r.user.keyboard("t");
    const dv = await screen.findByTestId("diff-view");
    expect(within(dv).getByLabelText("removed: 0.25")).toHaveAttribute("data-seg", "del-bad");
    expect(within(dv).getByLabelText("inserted: 0.99")).toHaveAttribute("data-seg", "ins-bad");
  });

  it("disables the diff when no cleanup ran, and takes an edited block's diff from its human edit", async () => {
    await mountVerify(2, (f) => {
      f.details[vid(1)] = makeBlockDetail(f.items[0], {}, { clean_text: null, faithfulness: null });
      f.details[vid(2)] = makeBlockDetail(f.items[1], {
        history: [{ decision: { id: "d1" } as never, action_id: 1, doc_id: "doc", raw_sha256: "x", shown_text_sha256: "y", numbers_verified: false, learning_provenance: "baseline", source: "human", human_edit_diff: [op("equal", true, "a ", "a "), op("insert", true, "", "HUMAN")] }],
      }, { status: "edited" });
    });
    await waitFor(() => expect(screen.getByTestId("view-diff")).toBeDisabled());
  });

  it("M4 a confirmed content-change edit shows a distinct marker; a faithful edit does not", async () => {
    const rec = (faith: boolean | null) => ({ decision: { id: "d1" } as never, action_id: 1, doc_id: "doc", raw_sha256: "x", shown_text_sha256: "y", numbers_verified: false, learning_provenance: "baseline", source: "human" as const, faith_passed: faith, human_edit_diff: [op("equal", true, "a ", "a "), op("insert", false, "", "999")] });
    const { r } = await mountVerify(3, (f) => {
      f.details[vid(1)] = makeBlockDetail(f.items[0], { history: [rec(false)] }, { status: "edited" });
      f.details[vid(2)] = makeBlockDetail(f.items[1], { history: [rec(true)] }, { status: "edited" });
    });
    expect(await screen.findByTestId("content-change-marker")).toHaveTextContent("human edit: content changed");
    await r.user.keyboard("j");
    await waitFor(() => expect(screen.getByTestId("block-id")).toHaveTextContent(vid(2)));
    expect(screen.queryByTestId("content-change-marker")).toBeNull();
  });

  it("lists why this needs you in server order with detail strings and a numeric rule line", async () => {
    await mountVerify(1, (f) => {
      f.items = [makeQueueItem(1, { has_numeric_spec: true })];
      f.details[vid(1)] = makeBlockDetail(f.items[0], {
        why: [
          { kind: "signal", name: "parser_agreement", value: 0.31, critical: true, detail: "pymupdf vs docling 0.31; numeric: '+0.05' vs '±0.05'" },
          { kind: "signal", name: "has_numeric_spec", value: 0, critical: false, detail: "numeric spec: 0.25 mm (always reviewed)" },
          { kind: "signal", name: "ocr_mean", value: 0.62, critical: false, detail: "mean over 12 words" },
        ],
      }, { has_numeric_spec: true });
    });
    const items = await screen.findAllByTestId("why-item");
    expect(items[0]).toHaveTextContent(/parsers disagree · 0\.31 of 1 · critical/);
    // the scorer's reader keys in the readers' names (design 09 section 14)
    expect(items[0]).toHaveTextContent("PDF text layer vs Layout parser: 0.31; numbers differ: '+0.05' vs '±0.05'");
    expect(items[1]).toHaveTextContent("low OCR");
    expect(screen.getByTestId("why-rule")).toHaveTextContent("Rule: always reviewed");
  });

  it("M9.6 a late ack of an earlier approve does not steal focus from the open editor", async () => {
    let release!: () => void;
    const { f, r } = await mountVerify(4, (fk) => {
      fk.actionGate = new Promise<void>((res) => (release = res));
    });
    await cardFocused(vid(1));
    await r.user.keyboard("a");
    await cardFocused(vid(2));
    await r.user.keyboard("e");
    const ta = await screen.findByLabelText("Edit block text");
    await waitFor(() => expect(ta).toHaveFocus());
    release(); // the approve's ack (and its focus request) lands while the editor is open
    await waitFor(() => expect(f.actions).toHaveLength(1));
    await new Promise((res) => setTimeout(res, 150));
    expect(screen.getByLabelText("Edit block text")).toHaveFocus();
  });

  it("M9.6 a late ack of an earlier approve does not steal focus from the flag dialog", async () => {
    let release!: () => void;
    const { f, r } = await mountVerify(4, (fk) => {
      fk.actionGate = new Promise<void>((res) => (release = res));
    });
    await cardFocused(vid(1));
    await r.user.keyboard("a");
    await cardFocused(vid(2));
    await r.user.keyboard("f");
    const group = await screen.findByRole("radiogroup");
    await waitFor(() => expect(group).toHaveFocus());
    release();
    await waitFor(() => expect(f.actions).toHaveLength(1));
    await new Promise((res) => setTimeout(res, 150));
    expect(screen.getByRole("radiogroup")).toHaveFocus();
  });

  it("design 12 section 4: an open hover tooltip takes the first Esc (edit kept); the second Esc cancels the editor", async () => {
    const { r } = await mountVerify(3);
    await cardFocused(vid(1));
    await r.user.keyboard("e");
    const ta = await screen.findByLabelText("Edit block text");
    await waitFor(() => expect(ta).toHaveFocus());
    await r.user.keyboard(" kept");
    await r.user.hover(screen.getByRole("combobox", { name: "Sort" }));
    await screen.findByRole("tooltip", {}, { timeout: 2000 });
    await r.user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    expect((screen.getByLabelText("Edit block text") as HTMLTextAreaElement).value).toMatch(/ kept$/);
    await r.user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByLabelText("Edit block text")).toBeNull());
  });

  it("e edits, Ctrl+Enter posts the text and focus returns to the queue", async () => {
    const { f, r } = await mountVerify(3);
    await cardFocused(vid(1));
    await r.user.keyboard("e");
    const ta = await screen.findByLabelText("Edit block text");
    await waitFor(() => expect(ta).toHaveFocus());
    await r.user.keyboard(" more");
    await r.user.keyboard(ctrlEnter);
    await waitFor(() => expect(f.actions).toHaveLength(1));
    expect(f.actions[0]).toMatchObject({ kind: "edit", block_id: vid(1), confirm_content_change: false });
    expect(f.actions[0].text).toMatch(/ more$/);
    await cardFocused(vid(2));
    expect(screen.queryByLabelText("Edit block text")).toBeNull();
  });

  it("a 409 opens the conflict panel; Enter confirms with the same text and a new request id", async () => {
    const { f, r } = await mountVerify(3, (fk) => {
      fk.actionHook = (_a, n) => (n === 0 ? { status: 409, body: conflictBody } : null);
    });
    await r.user.keyboard("e");
    await r.user.keyboard(" 999");
    await r.user.keyboard(ctrlEnter);
    const panel = await screen.findByTestId("edit-conflict");
    expect(panel).toHaveTextContent("This edit changes content");
    expect(screen.getByTestId("numeric-changes")).toHaveTextContent("0.25 → 0.99");
    const confirm = screen.getByRole("button", { name: "Confirm content change" });
    await waitFor(() => expect(confirm).toHaveFocus());
    await r.user.keyboard("{Enter}");
    await waitFor(() => expect(f.actions).toHaveLength(2));
    expect(f.actions[1]).toMatchObject({ kind: "edit", confirm_content_change: true, text: f.actions[0].text });
    expect(f.actions[1].request_id).not.toBe(f.actions[0].request_id);
    await cardFocused(vid(2));
  });

  it("M9 the textarea has focus the moment edit mode mounts, even right after another action", async () => {
    const { r } = await mountVerify(4);
    await cardFocused(vid(1));
    await r.user.keyboard("a");
    await r.user.keyboard("e"); // pressed while the previous action's focus request is still pending
    const ta = await screen.findByLabelText("Edit block text");
    expect(ta).toHaveFocus();
    await new Promise((res) => requestAnimationFrame(() => res(null)));
    await new Promise((res) => setTimeout(res, 50));
    expect(screen.getByLabelText("Edit block text")).toHaveFocus();
  });

  it("M1 while the conflict panel is open the text is locked and Confirm sends exactly the 409 text", async () => {
    const { f, r } = await mountVerify(3, (fk) => {
      fk.actionHook = (_a, n) => (n === 0 ? { status: 409, body: conflictBody } : null);
    });
    await r.user.keyboard("e");
    await r.user.keyboard(" 999");
    await r.user.keyboard(ctrlEnter);
    await screen.findByTestId("edit-conflict");
    const ta = screen.getByLabelText("Edit block text") as HTMLTextAreaElement;
    expect(ta).toHaveAttribute("readonly");
    await r.user.click(ta);
    await r.user.keyboard(" EXTRA 12345");
    expect(ta.value).not.toContain("EXTRA");
    await r.user.click(screen.getByRole("button", { name: "Confirm content change" }));
    await waitFor(() => expect(f.actions).toHaveLength(2));
    expect(f.actions[1].text).toBe(f.actions[0].text);
    expect(f.actions[1].text).toMatch(/ 999$/);
    expect(f.actions[1].text).not.toContain("EXTRA");
  });

  it("M1 Esc inside the locked textarea dismisses the panel and unlocks editing", async () => {
    const { r } = await mountVerify(3, (fk) => {
      fk.actionHook = (_a, n) => (n === 0 ? { status: 409, body: conflictBody } : null);
    });
    await r.user.keyboard("e");
    await r.user.keyboard(" 999");
    await r.user.keyboard(ctrlEnter);
    await screen.findByTestId("edit-conflict");
    const ta = screen.getByLabelText("Edit block text") as HTMLTextAreaElement;
    ta.focus();
    await r.user.keyboard("{Escape}");
    expect(screen.queryByTestId("edit-conflict")).toBeNull();
    expect(screen.getByLabelText("Edit block text")).not.toHaveAttribute("readonly");
  });

  it("M7 a 422 on edit shows the server message, not 'Not saved'", async () => {
    const { r } = await mountVerify(3, (fk) => {
      fk.actionHook = () => ({ status: 422, body: { detail: "edit text must not be empty", code: "invalid" } });
    });
    await r.user.keyboard("e");
    await r.user.keyboard("x");
    await r.user.keyboard(ctrlEnter);
    const err = await screen.findByTestId("edit-error");
    expect(err).toHaveTextContent("edit text must not be empty");
    expect(err).not.toHaveTextContent("Not saved");
    expect(screen.getByTestId("save-state")).not.toHaveTextContent("Not saved");
  });

  it("Keep editing returns to the textarea with the text intact", async () => {
    const { f, r } = await mountVerify(3, (fk) => {
      fk.actionHook = (_a, n) => (n === 0 ? { status: 409, body: conflictBody } : null);
    });
    await r.user.keyboard("e");
    await r.user.keyboard("ZZ");
    await r.user.keyboard(ctrlEnter);
    await screen.findByTestId("edit-conflict");
    await r.user.click(screen.getByRole("button", { name: "Keep editing" }));
    const ta = screen.getByLabelText("Edit block text") as HTMLTextAreaElement;
    expect(ta.value).toMatch(/ZZ$/);
    await waitFor(() => expect(ta).toHaveFocus());
    expect(f.actions).toHaveLength(1);
  });

  it("shows a 422 inline and stays in edit mode", async () => {
    const { r } = await mountVerify(3, (fk) => {
      fk.actionHook = () => ({ status: 422, body: { detail: "edit text must not be empty", code: "invalid" } });
    });
    await r.user.keyboard("e");
    await r.user.keyboard("{Control>}a{/Control}{Backspace}");
    await r.user.keyboard(ctrlEnter);
    expect(await screen.findByTestId("edit-error")).toHaveTextContent("edit text must not be empty");
    expect(screen.getByLabelText("Edit block text")).toBeInTheDocument();
  });

  it("Esc cancels the edit and drops the draft", async () => {
    const { f, r } = await mountVerify(3);
    await r.user.keyboard("e");
    await screen.findByLabelText("Edit block text");
    await r.user.keyboard("junk{Escape}");
    expect(screen.queryByLabelText("Edit block text")).toBeNull();
    await cardFocused(vid(1));
    expect(f.actions).toHaveLength(0);
  });

  it("edit mode swallows the other keys", async () => {
    const { f, r } = await mountVerify(3);
    await r.user.keyboard("e");
    await screen.findByLabelText("Edit block text");
    await r.user.keyboard("afjk1t");
    expect(f.actions).toHaveLength(0);
    expect((screen.getByLabelText("Edit block text") as HTMLTextAreaElement).value).toMatch(/afjk1t$/);
  });

  it("shows a figure block's image and disables Edit", async () => {
    const { r } = await mountVerify(2, (f) => {
      f.items = [makeQueueItem(1, { type: "figure" }), makeQueueItem(2)];
      f.details[vid(1)] = makeBlockDetail(f.items[0], { figures: [makeRailItem("FIG-doc-p001-01", "doc--a", "caption_ref", { block_id: vid(1) })] }, { raw_text: "", figure_id: "FIG-doc-p001-01" });
    });
    const fb = await screen.findByTestId("figure-block");
    expect(within(fb).getByRole("img")).toHaveAttribute("src", "/api/figures/FIG-doc-p001-01/image?v=abc123");
    expect(fb).toHaveTextContent("Caption of FIG-doc-p001-01");
    await r.user.keyboard("e");
    expect(screen.queryByLabelText("Edit block text")).toBeNull();
    expect(screen.getByTestId("act-edit")).toBeDisabled();
  });
});

describe("VC5 LearningChip", () => {
  it("only appears with learned rules or examples; Disable posts the id; re-run posts a job", async () => {
    const { f, scope, r } = await mountVerify(2, (fk) => {
      fk.details[vid(2)] = makeBlockDetail(fk.items[1], { learning: { provenance: "snap-3", learned_rules: ["rule-7"], few_shot: ["ex-2"] } });
    });
    await screen.findByTestId("block-text");
    expect(screen.queryByTestId("learning-chip")).toBeNull();
    await r.user.keyboard("a");
    const chip = await screen.findByRole("button", { name: /Why did this change\? learned \(snap-3\)/ });
    await r.user.click(chip);
    await r.user.click(screen.getByRole("button", { name: "Disable rule-7" }));
    await waitFor(() => expect(f.disables).toEqual(["rule-7"]));
    const note = await screen.findByTestId("learning-notice");
    expect(note).toHaveTextContent("Learning updated. Re-run cleanup to apply");
    expect(scope.log).not.toContain("POST /api/jobs");
    await r.user.click(within(note).getByRole("button", { name: "Re-run cleanup" }));
    await waitFor(() => expect(scope.log).toContain("POST /api/jobs"));
  });
});

const docFig = (n: number, attachments: DocFigure["attachments"]): DocFigure => ({
  figure_id: `FIG-doc-p001-0${n}`,
  block_id: `b-doc-p001-8${n}`,
  record: makeRecord(`FIG-doc-p001-0${n}`),
  image_url: `/api/figures/FIG-doc-p001-0${n}/image`,
  attachments,
  status: "queued",
});
const A = "doc--a";
const B = "doc--b";
const att = (a: string, rule = "proximity") => ({ article_id: a, rule, confidence: 0.8, anchor_block_id: null });

async function railSetup() {
  const s = await mountVerify(3, (f) => {
    f.rail[A] = [makeRailItem("FIG-doc-p001-01", A)];
    f.docFigures = [docFig(1, [att(A, "caption_ref")]), docFig(2, [att(B)])];
  });
  await s.r.user.keyboard("g");
  return s;
}

describe("VC6 FigureRail and FigurePicker", () => {
  it("shows the rail item's fields and a cache-busted thumbnail", async () => {
    await mountVerify(2, (f) => {
      f.rail[A] = [makeRailItem("FIG-doc-p001-01", A)];
    });
    const item = await screen.findByTestId("rail-item-FIG-doc-p001-01");
    expect(within(item).getByRole("img")).toHaveAttribute("src", "/api/figures/FIG-doc-p001-01/image?v=abc123");
    expect(item).toHaveTextContent("FIG-doc-p001-01");
    expect(item).toHaveTextContent("Caption of FIG-doc-p001-01");
    expect(within(item).getByTestId("rail-rule")).toHaveTextContent("caption_ref");
    expect(item).toHaveTextContent("native");
  });

  it("g focuses the rail; the picker lists the document's figures; attach posts, shows human + pending, then settles", async () => {
    const { f, scope, r } = await railSetup();
    await waitFor(() => expect(screen.getByTestId("rail-attach")).toHaveFocus());
    scope.jobById["job-a1"] = makeJob({ id: "job-a1", status: "running" });
    scope.jobById["job-d1"] = makeJob({ id: "job-d1", status: "running" });
    await r.user.keyboard("{Enter}");
    const picker = await screen.findByTestId("figure-picker");
    expect(await within(picker).findByTestId("pick-FIG-doc-p001-02")).toHaveTextContent("proximity");
    await r.user.keyboard("p001-02{ArrowDown}{Enter}");
    await waitFor(() => expect(f.attaches).toHaveLength(1));
    expect(f.attaches[0]).toEqual({ fid: "FIG-doc-p001-02", article_id: A, anchor: vid(1) });
    await waitFor(() => expect(f.detaches).toEqual([{ fid: "FIG-doc-p001-02", article_id: B }]));
    const item = await screen.findByTestId("rail-item-FIG-doc-p001-02");
    expect(within(item).getByTestId("rail-rule")).toHaveTextContent("human");
    expect(within(item).getByTestId("rail-pending")).toBeInTheDocument();
    expect(screen.queryByTestId("figure-picker")).toBeNull();
    // the job finishes; the server's rail now lists the figure with rule human
    f.rail[A] = [makeRailItem("FIG-doc-p001-01", A), makeRailItem("FIG-doc-p001-02", A, "human")];
    scope.jobById["job-a1"].status = "done";
    scope.jobById["job-d1"].status = "done";
    await waitFor(() => expect(within(screen.getByTestId("rail-item-FIG-doc-p001-02")).queryByTestId("rail-pending")).toBeNull(), { timeout: 4000 });
    expect(within(screen.getByTestId("rail-item-FIG-doc-p001-02")).getByTestId("rail-rule")).toHaveTextContent("human");
  });

  for (const mode of ["loading", "error"] as const)
    it(`M10 the picker passes axe while ${mode} (the listbox holds options only)`, async () => {
      const { r } = await railSetup();
      server.use(
        http.get("*/api/docs/:slug/figures", async () => {
          if (mode === "loading") await delay(1500);
          return HttpResponse.json({ detail: "boom", code: "internal" }, { status: 500 });
        }),
      );
      await r.user.keyboard("{Enter}");
      const picker = await screen.findByTestId("figure-picker");
      if (mode === "error") await within(picker).findByText("Could not load figures", undefined, { timeout: 4000 });
      else await within(picker).findByText("Loading figures...");
      for (const child of Array.from(picker.querySelectorAll("#picker-list > *"))) expect(child.getAttribute("role")).toBe("option");
      const res = await axe.run(picker, { runOnly: ["aria-required-children", "aria-required-parent", "aria-allowed-role"] });
      expect(res.violations.map((v) => v.id)).toEqual([]);
    }, 10000);

  it("M10 the picker passes axe with figures and with an empty filter result", async () => {
    const { r } = await railSetup();
    await r.user.keyboard("{Enter}");
    const picker = await screen.findByTestId("figure-picker");
    await screen.findByTestId("pick-FIG-doc-p001-02");
    const run = async (): Promise<string[]> => (await axe.run(picker, { runOnly: ["aria-required-children", "aria-required-parent", "aria-allowed-role"] })).violations.map((v) => v.id);
    expect(await run()).toEqual([]);
    await r.user.type(screen.getByLabelText("Filter figures"), "no-such-figure");
    expect(await run()).toEqual([]);
  });

  it("without 'also detach' only the attach is posted", async () => {
    const { f, scope, r } = await railSetup();
    scope.jobById["job-a1"] = makeJob({ id: "job-a1", status: "running" });
    await r.user.keyboard("{Enter}");
    await screen.findByTestId("pick-FIG-doc-p001-02");
    await r.user.click(screen.getByLabelText("Also detach from its other articles"));
    await r.user.keyboard("p001-02{ArrowDown}{Enter}");
    await waitFor(() => expect(f.attaches).toHaveLength(1));
    expect(f.detaches).toHaveLength(0);
  });

  it("M2 an attach whose job finishes while the rail is unmounted shows up when the user navigates back", async () => {
    const { f, scope, r } = await mountVerify(3, (fk) => {
      fk.rail[A] = [makeRailItem("FIG-doc-p001-01", A)];
      fk.rail[B] = [];
      fk.docFigures = [docFig(1, [att(A, "caption_ref")]), docFig(2, [att(B)])];
      fk.details[vid(2)] = makeBlockDetail(fk.items[1], { article_ids: [B] });
    });
    await r.user.keyboard("g");
    scope.jobPolls = [[makeJob({ id: "job-a1", status: "running" })]];
    scope.jobById["job-a1"] = makeJob({ id: "job-a1", status: "running" });
    await r.user.keyboard("{Enter}");
    await screen.findByTestId("pick-FIG-doc-p001-02");
    await r.user.click(screen.getByLabelText("Also detach from its other articles"));
    await r.user.keyboard("p001-02{ArrowDown}{Enter}");
    await waitFor(() => expect(f.attaches).toHaveLength(1));
    // leave the block: article A's rail unmounts while the job is still running
    await r.user.keyboard("{Escape}");
    await cardFocused(vid(1));
    await r.user.keyboard("j");
    await screen.findByRole("region", { name: `Figures in ${B}` });
    expect(screen.queryByRole("region", { name: `Figures in ${A}` })).toBeNull();
    // the job finishes while A's rail is not mounted
    f.rail[A] = [makeRailItem("FIG-doc-p001-01", A), makeRailItem("FIG-doc-p001-02", A, "human")];
    scope.jobById["job-a1"] = makeJob({ id: "job-a1", status: "done" });
    scope.jobPolls.splice(0, scope.jobPolls.length, []);
    await r.user.keyboard("k");
    const item = await screen.findByTestId("rail-item-FIG-doc-p001-02", undefined, { timeout: 6000 });
    expect(within(item).getByTestId("rail-rule")).toHaveTextContent("human");
    expect(within(item).queryByTestId("rail-pending")).toBeNull();
  }, 20000);

  it("rolls the optimistic attach back and toasts when the job fails", async () => {
    const { scope, r } = await railSetup();
    scope.jobById["job-a1"] = makeJob({ id: "job-a1", status: "failed", error: "cleanup crashed" });
    scope.jobById["job-d1"] = makeJob({ id: "job-d1", status: "failed", error: "cleanup crashed" });
    await r.user.keyboard("{Enter}");
    await screen.findByTestId("pick-FIG-doc-p001-02");
    await r.user.keyboard("p001-02{ArrowDown}{Enter}");
    expect(await screen.findByText(/Figure change failed: cleanup crashed/, undefined, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("rail-item-FIG-doc-p001-02")).toBeNull());
  });

  it("Esc closes the picker and returns focus to the attach button", async () => {
    const { r } = await railSetup();
    await r.user.keyboard("{Enter}");
    await screen.findByTestId("figure-picker");
    await r.user.keyboard("{Escape}");
    expect(screen.queryByTestId("figure-picker")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("rail-attach")).toHaveFocus());
  });

  it("x detaches the focused figure and greys it as pending", async () => {
    const { f, scope, r } = await railSetup();
    scope.jobById["job-d1"] = makeJob({ id: "job-d1", status: "running" });
    await r.user.keyboard("{ArrowDown}");
    await waitFor(() => expect(screen.getByTestId("rail-item-FIG-doc-p001-01")).toHaveFocus());
    await r.user.keyboard("x");
    await waitFor(() => expect(f.detaches).toEqual([{ fid: "FIG-doc-p001-01", article_id: A }]));
    expect(within(screen.getByTestId("rail-item-FIG-doc-p001-01")).getByTestId("rail-pending")).toBeInTheDocument();
  });

  it("c opens the crop editor: validates the box, then PUTs the bbox", async () => {
    const { f, r } = await railSetup();
    f.items.push(makeQueueItem(4));
    f.details["b-doc-p001-01"] = makeBlockDetail(makeQueueItem(1, { block_id: "b-doc-p001-01" }));
    await r.user.keyboard("{ArrowDown}c");
    const form = await screen.findByTestId("crop-editor");
    expect(screen.getByTestId("crop-box")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Crop handle/ })).toHaveLength(4);
    const x1 = within(form).getByLabelText("x1") as HTMLInputElement;
    await r.user.clear(x1);
    await r.user.type(x1, "20");
    expect(await within(form).findByTestId("crop-error")).toHaveTextContent(/at least 4 pt|inside/);
    expect(within(form).getByRole("button", { name: "Save crop" })).toBeDisabled();
    await r.user.clear(x1);
    await r.user.type(x1, "300");
    expect(within(form).queryByTestId("crop-error")).toBeNull();
    await r.user.click(within(form).getByRole("button", { name: "Save crop" }));
    await waitFor(() => expect(f.bboxes).toEqual([{ fid: "FIG-doc-p001-01", bbox: [50, 60, 300, 260] }]));
  });
});

describe("VC7 FlagDialog", () => {
  it("starts on the radiogroup; digits pick a category without leaving the screen; Tab goes to the note; Ctrl+Enter submits", async () => {
    const { f, r } = await mountVerify(3);
    await cardFocused(vid(1));
    await r.user.keyboard("f");
    const dlg = await screen.findByRole("dialog", { name: "Flag block" });
    await waitFor(() => expect(within(dlg).getByRole("radiogroup")).toHaveFocus());
    await r.user.keyboard("2");
    expect(r.router.state.location.pathname).toBe("/verify");
    expect(within(dlg).getByTestId("flag-cat-missing_figure")).toHaveAttribute("aria-checked", "true");
    await r.user.keyboard("{Tab}");
    expect(screen.getByLabelText("Note (optional)")).toHaveFocus();
    await r.user.keyboard("1a j k");
    await r.user.keyboard(ctrlEnter);
    await waitFor(() => expect(f.actions).toHaveLength(1));
    expect(f.actions[0]).toMatchObject({ kind: "flag", block_id: vid(1), flag: { category: "missing_figure", note: "1a j k" } });
    await cardFocused(vid(2));
  });

  it("Enter without a category says so; with one, Enter submits and the note is null", async () => {
    const { f, r } = await mountVerify(3);
    await r.user.keyboard("f");
    await screen.findByRole("dialog", { name: "Flag block" });
    await r.user.keyboard("{Enter}");
    expect(screen.getByTestId("flag-msg")).toHaveTextContent("Choose a category");
    expect(f.actions).toHaveLength(0);
    await r.user.keyboard("5{Enter}");
    await waitFor(() => expect(f.actions).toHaveLength(1));
    expect(f.actions[0].flag).toEqual({ category: "table_structure", note: null, target_id: null });
  });

  it("Esc cancels and the dialog traps Tab", async () => {
    const { f, r } = await mountVerify(3);
    await r.user.keyboard("f");
    const dlg = await screen.findByRole("dialog", { name: "Flag block" });
    for (let i = 0; i < 6; i++) await r.user.keyboard("{Tab}");
    expect(dlg.contains(document.activeElement)).toBe(true);
    await r.user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Flag block" })).toBeNull();
    await cardFocused(vid(1));
    expect(f.actions).toHaveLength(0);
    expect(card(vid(1))).toBeInTheDocument();
  });

  it("a bad_crop flag on a figure block targets the figure", async () => {
    const { f, r } = await mountVerify(2, (fk) => {
      fk.items = [makeQueueItem(1, { type: "figure" }), makeQueueItem(2)];
      fk.details[vid(1)] = makeBlockDetail(fk.items[0], {}, { figure_id: "FIG-doc-p001-01", raw_text: "" });
    });
    await screen.findByTestId("figure-block");
    await r.user.keyboard("f4{Enter}");
    await waitFor(() => expect(f.actions).toHaveLength(1));
    expect(f.actions[0].flag).toMatchObject({ category: "bad_crop", target_id: "FIG-doc-p001-01" });
  });
});
