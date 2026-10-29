// VC1 status strip, VC2 queue, VC3 source pane, VC8 screen integration, VC9 action bar.
import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { counts, cursor, makeBlockDetail, makeQueueItem, ready, vid, seedQueue } from "../test/verifyFake";
import { card, cardFocused, mountVerify } from "./helpers.test-util";

const options = () => within(screen.getByRole("listbox", { name: "Review queue" })).queryAllByRole("option");

describe("VC1 StatusStrip", () => {
  it("shows the counts, readiness chips and a slider that starts at the project threshold", async () => {
    await mountVerify(12, (f) => {
      f.counts = counts({ pending: 12, auto_approved: 5, approved: 3, edited: 1, flagged_open: 2, in_scope: 30 });
      f.docs = [ready("doc"), { doc_id: "late", state: "pending", stale: false, waiting_for: "score" }, { doc_id: "redo", state: "ready", stale: true, waiting_for: null }];
    });
    await waitFor(() => expect(screen.getByTestId("cnt-queued")).toHaveTextContent("12"));
    expect(screen.getByTestId("cnt-auto")).toHaveTextContent("5");
    expect(screen.getByTestId("cnt-flagged")).toHaveTextContent("2");
    expect(screen.getByTestId("cnt-done")).toHaveTextContent("4");
    expect(screen.getByTestId("cnt-scope")).toHaveTextContent("30");
    const slider = screen.getByLabelText("Also review auto-approved blocks below") as HTMLInputElement;
    expect(slider.min).toBe("0.85");
    expect(slider.max).toBe("1");
    expect(screen.getByTestId("view-copy")).toHaveTextContent("Only blocks under the 0.85 threshold");
    const chips = screen.getAllByTestId("doc-chip").map((c) => c.textContent);
    expect(chips).toEqual(["late: preparing (score)", "redo: re-scoring"]);
  });

  it("[ and ] step the view filter and send one debounced cursor PUT with all four fields", async () => {
    const { f, r } = await mountVerify(5);
    await r.user.keyboard("]]");
    expect(screen.getByTestId("view-copy")).toHaveTextContent(/below 0\.95/);
    await waitFor(() => expect(f.cursors).toHaveLength(1));
    expect(f.cursors[0]).toMatchObject({ sort: "worst_first", view_threshold: 0.95, doc_filter: null, current_block_id: vid(1) });
    expect(typeof f.cursors[0].request_id).toBe("string");
    await waitFor(() => expect(f.queueReqs.some((q) => q.includes("view_threshold=0.95"))).toBe(true));
    await r.user.keyboard("{[}{[}");
    await waitFor(() => expect(f.cursors).toHaveLength(2));
    expect(f.cursors[1].view_threshold).toBeNull();
    expect(screen.getByTestId("view-copy")).toHaveTextContent(/Only blocks under/);
  });

  it("/ cycles the sort, saves the cursor and refetches the queue", async () => {
    const { f, r } = await mountVerify(5);
    await r.user.keyboard("/");
    await waitFor(() => expect(f.cursors[f.cursors.length - 1]?.sort).toBe("by_page"));
    await waitFor(() => expect(f.queueReqs.some((q) => q.includes("sort=by_page"))).toBe(true));
    expect((screen.getByLabelText("Sort") as HTMLSelectElement).value).toBe("by_page");
    expect(screen.getByTestId("save-state")).toHaveTextContent("Saved");
  });

  it("counts the auto-approved blocks the view filter added out of the queued number", async () => {
    await mountVerify(4, (f) => {
      f.items = [makeQueueItem(1), makeQueueItem(2), makeQueueItem(3, { status: "auto_approved", confidence: 0.9 }), makeQueueItem(4, { status: "auto_approved", confidence: 0.92 })];
      f.cursor = cursor({ view_threshold: 0.95 });
      f.counts = counts({ pending: 4, auto_approved: 2, in_scope: 9 });
    });
    await waitFor(() => expect(screen.getByTestId("cnt-queued")).toHaveTextContent("2"));
    expect(screen.getByTestId("view-copy")).toHaveTextContent("Showing 2 auto-approved blocks below 0.95");
  });
});

describe("VC1 counts honesty (G1: no server view_added yet)", () => {
  it("M3 with more pages than loaded, Queued is derived from the server counts and marked partial, never 1100", async () => {
    // 1,200 listed in the view, 200 of them auto-approved; only the first page of 500 is loaded and it holds 100 of them
    await mountVerify(1200, (f) => {
      f.items = Array.from({ length: 1200 }, (_, i) => makeQueueItem(i + 1, i < 100 || (i >= 600 && i < 700) ? { status: "auto_approved", confidence: 0.9 } : {}));
      f.cursor = cursor({ view_threshold: 0.95 });
      f.counts = counts({ pending: 1200, auto_approved: 200, in_scope: 1500 });
    });
    await waitFor(() => expect(screen.getByTestId("cnt-queued")).toHaveTextContent("1000+"));
    expect(screen.getByTestId("cnt-queued")).not.toHaveTextContent("1100");
    expect(screen.getByTestId("view-copy")).toHaveTextContent("Showing 100+ auto-approved blocks below 0.95 (loaded)");
  });

  it("M3 with the view filter off, Queued is exactly the server's pending count", async () => {
    await mountVerify(1200, (f) => {
      f.counts = counts({ pending: 1200, auto_approved: 200, in_scope: 1500 });
    });
    await waitFor(() => expect(screen.getByTestId("cnt-queued")).toHaveTextContent(/^1200$/));
  });
});

describe("VC2 resume beyond the first page", () => {
  it("M5 a saved cursor on page 2 loads pages up to the cursor's page and lists it (not pinned); no further pages are fetched", async () => {
    const { f } = await mountVerify(1200, (fk) => {
      fk.cursor = cursor({ current_block_id: vid(700) });
    });
    await waitFor(() => expect(f.queueReqs.some((q) => q.includes("offset=500"))).toBe(true));
    // the list now contains the cursor block, so the pinned copy is gone (rows are virtualised: no card lookup)
    await waitFor(() => expect(document.querySelector("[data-pinned='true']")).toBeNull());
    expect(screen.getByTestId("block-id")).toHaveTextContent(vid(700));
    expect(f.queueReqs.some((q) => q.includes("offset=1000"))).toBe(false);
  });

  it("M5 an already-approved cursor block (not queued) does not pull in every page", async () => {
    const { f } = await mountVerify(1200, (fk) => {
      fk.cursor = cursor({ current_block_id: vid(900) });
      fk.details[vid(900)] = makeBlockDetail(makeQueueItem(900, { status: "approved" }));
    });
    await screen.findByTestId(`card-${vid(900)}`);
    await new Promise((r) => setTimeout(r, 300));
    expect(f.queueReqs.some((q) => q.includes("offset=500"))).toBe(false);
    expect(card(vid(900))).toHaveAttribute("data-pinned", "true");
  });
});

describe("VC2 Queue", () => {
  it("virtualises 1,500 items into a few option nodes and exposes set size", async () => {
    await mountVerify(1500);
    expect(options().length).toBeGreaterThan(5);
    expect(options().length).toBeLessThanOrEqual(60);
    expect(screen.getByRole("listbox", { name: "Review queue" })).toBeInTheDocument();
    expect(options()[0]).toHaveAttribute("aria-setsize", "1500");
  });

  it("uses roving tabindex and arrows browse and save the cursor, debounced", async () => {
    const { f, r } = await mountVerify(6);
    await cardFocused(vid(1));
    expect(card(vid(1))).toHaveAttribute("tabindex", "0");
    expect(card(vid(2))).toHaveAttribute("tabindex", "-1");
    await r.user.keyboard("{ArrowDown}{ArrowDown}");
    await cardFocused(vid(3));
    expect(card(vid(3))).toHaveAttribute("aria-selected", "true");
    expect(card(vid(1))).toHaveAttribute("aria-selected", "false");
    expect(f.cursors).toHaveLength(0);
    await waitFor(() => expect(f.cursors).toHaveLength(1));
    expect(f.cursors[0].current_block_id).toBe(vid(3));
    await r.user.keyboard("{End}");
    await cardFocused(vid(6));
    await r.user.keyboard("{Home}");
    await cardFocused(vid(1));
    await r.user.click(card(vid(4)));
    expect(card(vid(4))).toHaveAttribute("aria-selected", "true");
  });

  it("shows status chips for changed-since-approval and re-scoring, and the pinned card", async () => {
    await mountVerify(
      3,
      (f) => {
        f.items = [
          makeQueueItem(1, { reasons: ["changed since approval", "ocr_mean"], status: "queued" }),
          makeQueueItem(2, { stale_doc: true }),
          makeQueueItem(3, { has_numeric_spec: true, reasons: ["parser_agreement", "ocr_min", "faithfulness", "has_numeric_spec"].slice(0, 3) }),
        ];
        f.cursor = cursor({ current_block_id: vid(9, 4) });
        f.details[vid(9, 4)] = makeBlockDetail(makeQueueItem(9, { page: 4, block_id: vid(9, 4), status: "approved" }));
      },
    );
    const pinned = await screen.findByTestId(`card-${vid(9, 4)}`);
    expect(pinned).toHaveAttribute("data-pinned", "true");
    expect(pinned).toHaveAttribute("aria-selected", "true");
    expect(within(pinned).getByText("approved")).toBeInTheDocument();
    expect(within(card(vid(1))).getByText("changed since approval")).toBeInTheDocument();
    expect(within(card(vid(2))).getByText("re-scoring")).toBeInTheDocument();
    expect(within(card(vid(3))).getByText("numeric spec")).toBeInTheDocument();
  });

  it("explains pending documents and offers links when the queue is empty", async () => {
    await mountVerify(
      0,
      (f) => {
        f.docs = [ready("doc"), { doc_id: "late", state: "pending", stale: false, waiting_for: "score" }];
        f.counts = counts({ flagged_open: 2 });
      },
    ).catch(() => undefined);
    expect(await screen.findByTestId("queue-empty")).toHaveTextContent("All caught up");
    expect(screen.getByRole("link", { name: "Go to Agent" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Export" })).toBeInTheDocument();
    expect(screen.getByTestId("queue-footer")).toHaveTextContent("1 document still preparing");
  });
});

describe("VC3 SourcePane", () => {
  const withPage = (f: Parameters<NonNullable<Parameters<typeof mountVerify>[1]>>[0]) => {
    f.pageBlocks["doc:1"] = [
      { block_id: "b-doc-p001-90", bbox: [10, 10, 100, 20], type: "header", status: "auto_approved" },
      { block_id: vid(1), bbox: [61.2, 79.2, 306, 396], type: "paragraph", status: "queued" },
      { block_id: vid(2), bbox: [61.2, 400, 306, 500], type: "paragraph", status: "queued" },
    ];
  };

  it("loads the server page image, zooms to 300 dpi and outlines the current block", async () => {
    const { r } = await mountVerify(3, withPage);
    const img = (await screen.findByAltText("Page 1 of doc")) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("/api/docs/doc/pages/1.png?dpi=150");
    const rect = await screen.findByTestId(`rect-${vid(1)}`);
    expect(rect).toHaveAttribute("data-current", "true");
    expect(rect.style.left).toBe("10%");
    expect(rect.style.top).toBe("10%");
    expect(rect.style.width).toBe("40%");
    expect(rect.style.height).toBe("40%");
    expect(screen.getByTestId("rect-b-doc-p001-90")).toBeDisabled();
    await r.user.keyboard("z");
    await waitFor(() => expect(img.getAttribute("src")).toBe("/api/docs/doc/pages/1.png?dpi=300"));
  });

  it("M6 overlays are stacked largest first, so a block inside a table or figure is on top and clickable", async () => {
    const { r } = await mountVerify(3, (f) => {
      f.pageBlocks["doc:1"] = [
        { block_id: vid(2), bbox: [100, 120, 200, 160], type: "paragraph", status: "queued" }, // small, inside the table
        { block_id: vid(1), bbox: [61.2, 79.2, 306, 396], type: "table", status: "queued" }, // large, listed after the small one
        { block_id: vid(3), bbox: [10, 600, 100, 650], type: "paragraph", status: "queued" },
      ];
    });
    const big = await screen.findByTestId(`rect-${vid(1)}`);
    const small = screen.getByTestId(`rect-${vid(2)}`);
    // later in the DOM paints on top
    expect(big.compareDocumentPosition(small) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await r.user.click(small);
    await waitFor(() => expect(screen.getByTestId("block-id")).toHaveTextContent(vid(2)));
  });

  it("a click or Enter on a rect makes it current", async () => {
    const { r } = await mountVerify(3, withPage);
    await r.user.click(await screen.findByTestId(`rect-${vid(2)}`));
    await waitFor(() => expect(screen.getByTestId("block-id")).toHaveTextContent(vid(2)));
    await r.user.keyboard("s");
    await waitFor(() => expect(screen.getByTestId(`rect-${vid(2)}`)).toHaveFocus());
    await r.user.keyboard("{ArrowLeft}");
    await waitFor(() => expect(screen.getByTestId(`rect-${vid(1)}`)).toHaveFocus());
    await r.user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("block-id")).toHaveTextContent(vid(1)));
  });

  it("toasts when a jump target is outside the selection", async () => {
    const { r } = await mountVerify(3, (f) => {
      withPage(f);
      f.pageBlocks["doc:1"].push({ block_id: "b-doc-p001-77", bbox: [10, 600, 100, 650], type: "paragraph", status: "queued" });
      f.detailErrors["b-doc-p001-77"] = { status: 422, detail: "out of scope" };
    });
    await r.user.click(await screen.findByTestId("rect-b-doc-p001-77"));
    expect(await screen.findByText("Not in your selection")).toBeInTheDocument();
    expect(screen.getByTestId("block-id")).toHaveTextContent(vid(1));
  });

  it("falls back to the parser text for Word documents", async () => {
    await mountVerify(2, (f) => {
      const d = makeBlockDetail(f.items[0]);
      d.page = { ...d.page, render_url: null, width: 0, height: 0 };
      f.details[f.items[0].block_id] = d;
    });
    expect(await screen.findByTestId("no-page-image")).toHaveTextContent("No page image for Word documents");
  });

  it("highlights the OCR words where the parsers disagree", async () => {
    await mountVerify(2, (f) => {
      withPage(f);
      const w = (text: string, i: number) => ({ text, confidence: 0.9, bbox: [70 + i * 30, 90, 95 + i * 30, 100] });
      f.details[vid(1)] = makeBlockDetail(f.items[0], {}, {
        raw_text_by_parser: { ocr: "set 0.25 mm now", ocr_alt: "set 0.35 mm now" },
        ocr_words: [w("set", 0), w("0.25", 1), w("mm", 2), w("now", 3)],
      });
    });
    const boxes = await screen.findAllByTestId("disagree-word");
    expect(boxes).toHaveLength(1);
    expect(screen.queryByTestId("disagree-block")).toBeNull();
  });

  it("hatches the whole block when there are no word boxes to map to", async () => {
    await mountVerify(2, (f) => {
      withPage(f);
      f.details[vid(1)] = makeBlockDetail(f.items[0], {}, { raw_text_by_parser: { pymupdf: "alpha beta", docling: "alpha gamma" } });
    });
    expect(await screen.findByTestId("disagree-block")).toBeInTheDocument();
  });
});

describe("VC8 VerifyScreen integration", () => {
  it("advances optimistically before the server answers", async () => {
    let release!: () => void;
    const { f, r } = await mountVerify(4, (fk) => {
      fk.actionGate = new Promise<void>((res) => (release = res));
    });
    await cardFocused(vid(1));
    await r.user.keyboard("a");
    await cardFocused(vid(2));
    expect(screen.queryByTestId(`card-${vid(1)}`)).toBeNull();
    expect(screen.getByTestId("save-state")).toHaveTextContent("Saving (1)");
    act(() => release());
    await waitFor(() => expect(screen.getByTestId("save-state")).toHaveTextContent("Saved"));
    expect(f.actions[0]).toMatchObject({ kind: "approve", block_id: vid(1) });
    expect(screen.getByTestId("cnt-done")).toHaveTextContent("1");
    await cardFocused(vid(2));
  });

  it("lets the server's next block win over the optimistic guess", async () => {
    let release!: () => void;
    const { f, r } = await mountVerify(5, (fk) => {
      fk.actionGate = new Promise<void>((res) => (release = res));
      fk.nextFor = (a) => (a.kind === "approve" ? makeQueueItem(4) : undefined);
    });
    await r.user.keyboard("a");
    await cardFocused(vid(2)); // the optimistic guess, before the server answers
    act(() => release());
    await waitFor(() => expect(f.actions).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId("save-state")).toHaveTextContent("Saved"));
    await waitFor(() => expect(card(vid(4))).toHaveAttribute("aria-selected", "true"));
    expect(card(vid(2))).toHaveAttribute("aria-selected", "false");
    await cardFocused(vid(4));
  });

  it("rolls back, toasts and returns focus when the server fails", async () => {
    const { f, r } = await mountVerify(4, (fk) => {
      fk.actionHook = () => ({ status: 500, body: { detail: "disk full", code: "internal" } });
    });
    await r.user.keyboard("a");
    expect(await screen.findByText(/Not saved: disk full/)).toBeInTheDocument();
    await waitFor(() => expect(card(vid(1))).toHaveAttribute("aria-selected", "true"));
    await cardFocused(vid(1));
    expect(f.actions).toHaveLength(1);
    expect(screen.getByTestId("save-state")).toHaveTextContent("Not saved");
  });

  it("sends three fast presses as three ordered POSTs with distinct ids", async () => {
    const { f, r } = await mountVerify(6);
    await r.user.keyboard("aaa");
    await waitFor(() => expect(f.actions).toHaveLength(3));
    expect(f.actions.map((a) => a.block_id)).toEqual([vid(1), vid(2), vid(3)]);
    expect(new Set(f.actions.map((a) => a.request_id)).size).toBe(3);
    await waitFor(() => expect(screen.getByTestId("save-state")).toHaveTextContent("Saved"));
    await cardFocused(vid(4));
  });

  it("k pins the block just left and focuses it", async () => {
    const { f, r } = await mountVerify(5);
    await r.user.keyboard("a");
    await cardFocused(vid(2));
    await waitFor(() => expect(screen.getByTestId("save-state")).toHaveTextContent("Saved"));
    await r.user.keyboard("k");
    await cardFocused(vid(1));
    expect(card(vid(1))).toHaveAttribute("data-pinned", "true");
    await waitFor(() => expect(f.actions.map((a) => a.kind)).toEqual(["approve", "back"]));
  });

  it("does not replace the queue with a server snapshot while writes are in flight", async () => {
    let release!: () => void;
    const { f, r } = await mountVerify(4, (fk) => {
      fk.actionGate = new Promise<void>((res) => (release = res));
    });
    await r.user.keyboard("a");
    await cardFocused(vid(2));
    const before = f.queueReqs.length;
    await act(async () => {
      await r.qc.invalidateQueries({ queryKey: ["verify", "queue"] });
    });
    expect(f.queueReqs.length).toBeGreaterThan(before); // fetched, but not applied
    expect(screen.queryByTestId(`card-${vid(1)}`)).toBeNull();
    act(() => release());
    await waitFor(() => expect(screen.getByTestId("save-state")).toHaveTextContent("Saved"));
    expect(screen.queryByTestId(`card-${vid(1)}`)).toBeNull();
  });

  it("a finished job invalidates the verify queries", async () => {
    const { f, r } = await mountVerify(3);
    const n = f.queueReqs.length;
    await act(async () => {
      await r.qc.invalidateQueries({ queryKey: ["verify"] });
    });
    await waitFor(() => expect(f.queueReqs.length).toBeGreaterThan(n));
  });
});

describe("VC9 ActionBar", () => {
  it("shows key hints and the buttons do what the keys do", async () => {
    const { f, r } = await mountVerify(4);
    const bar = screen.getByRole("toolbar", { name: "Review actions" });
    for (const k of ["A", "E", "F", "J", "K"]) expect(within(bar).getByText(k)).toBeInTheDocument();
    await r.user.click(within(bar).getByTestId("act-approve"));
    await waitFor(() => expect(f.actions[0]).toMatchObject({ kind: "approve", block_id: vid(1) }));
    await r.user.click(within(bar).getByTestId("act-skip"));
    await waitFor(() => expect(f.actions[1]).toMatchObject({ kind: "skip", block_id: vid(2) }));
    await r.user.click(within(bar).getByTestId("act-back"));
    await waitFor(() => expect(f.actions[2].kind).toBe("back"));
    await r.user.click(within(bar).getByTestId("act-edit"));
    expect(await screen.findByLabelText("Edit block text")).toBeInTheDocument();
  });

  it("disables everything but Back with no current block, and Edit on figure blocks", async () => {
    await mountVerify(0).catch(() => undefined);
    await screen.findByTestId("queue-empty");
    expect(screen.getByTestId("act-approve")).toBeDisabled();
    expect(screen.getByTestId("act-edit")).toBeDisabled();
    expect(screen.getByTestId("act-flag")).toBeDisabled();
    expect(screen.getByTestId("act-skip")).toBeDisabled();
    expect(screen.getByTestId("act-back")).toBeEnabled();
  });

  it("disables Edit for a figure block", async () => {
    await mountVerify(2, (f) => {
      f.items = [makeQueueItem(1, { type: "figure" }), makeQueueItem(2)];
      seedQueue;
    });
    await waitFor(() => expect(screen.getByTestId("act-edit")).toBeDisabled());
    expect(await screen.findByTestId("figure-block")).toBeInTheDocument();
  });
});
