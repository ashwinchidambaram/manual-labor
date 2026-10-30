// Module 12 fix round: what the Verify screen says about a block's score, its counts and why it is queued.
import { render, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { server } from "../test/server";
import { describe, expect, it } from "vitest";
import { counts, makeBlockDetail, makeQueueItem, vid } from "../test/verifyFake";
import { card, mountVerify } from "./helpers.test-util";
import StatusStrip from "./StatusStrip";

const strip = (c: ReturnType<typeof counts>) =>
  render(
    <StatusStrip counts={c} viewAdded={0} viewAddedPartial={false} appliedView={null} docs={[]} threshold={0.85} view={null} sort="worst_first" onView={() => undefined} onSort={() => undefined} saveState="Saved" />,
  );

describe("M12 trust: Verify counts", () => {
  it("the line uses the server's queued count and shows rejected as its own bucket", () => {
    strip(counts({ in_scope: 20, queued: 6, auto_approved: 8, approved: 3, edited: 1, flagged_open: 1, rejected: 1, pending: 6 }));
    expect(screen.getByTestId("reconcile-review")).toHaveTextContent("In scope 20 = 6 to review + 8 auto-approved + 4 done + 1 flagged + 1 rejected");
    expect(screen.queryByTestId("reconcile-mismatch")).toBeNull();
  });
  it("the mismatch warning fires when the independent fields disagree", () => {
    strip(counts({ in_scope: 20, queued: 7, auto_approved: 8, approved: 3, edited: 1, flagged_open: 1, rejected: 1 }));
    expect(screen.queryByTestId("reconcile-review")).toBeNull();
    expect(screen.getByTestId("reconcile-mismatch")).toHaveTextContent("Counts do not add up (in scope 20, but to review 7 + auto-approved 8 + done 4 + flagged 1 + rejected 1 = 21)");
  });
});

describe("M12 trust: scores carry their meaning", () => {
  it("every queue card and the header name the score and the threshold it is judged against", async () => {
    await mountVerify(3, (f) => {
      f.items = [makeQueueItem(1), makeQueueItem(2, { confidence: 0.9, has_numeric_spec: true, reasons: ["has_numeric_spec"] }), makeQueueItem(3, { confidence: null })];
    });
    expect(within(card(vid(1))).getByTestId("queue-score")).toHaveTextContent(/^score 0\.10 · below 0\.85$/);
    expect(within(card(vid(2))).getByTestId("queue-score")).toHaveTextContent(/^score 0\.90 · at or above 0\.85$/);
    expect(within(card(vid(3))).getByTestId("queue-score")).toHaveTextContent(/^score n\/a · not scored yet$/);
    expect(await screen.findByTestId("block-confidence")).toHaveTextContent(/^score 0\.10 · below 0\.85$/);
  });
});

describe("M12 trust: why a block that passed faithfulness is still queued", () => {
  it("the checks say it in one line, from the API's reasons", async () => {
    await mountVerify(2, (f) => {
      const it = f.items[0];
      f.details[it.block_id] = makeBlockDetail(it, {
        why: [
          { kind: "signal", name: "parser_agreement", value: 0.7, critical: false, detail: null },
          { kind: "signal", name: "has_numeric_spec", value: 0, critical: true, detail: null },
        ],
      });
    });
    expect(await screen.findByTestId("checks-queued-why")).toHaveTextContent("Queued because the parsers disagree on this block and it contains numbers, units or part numbers.");
  });
});

describe("M12 trust: an empty queue says what comes next", () => {
  it("export still locked: no 'Next: export', it says what still blocks", async () => {
    await mountVerify(0, (f) => (f.counts = counts({ in_scope: 9, queued: 4, auto_approved: 5 })), {
      exportStatus: { unlocked: false, open_flags: 0, queued: 4, blockers: ["b-doc-p002-01"], overrides: [], summary: null, zip_path: null },
    }).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty");
    expect(await within(empty).findByTestId("queue-next")).toHaveTextContent("Export is still locked: 4 blocks in scope still need review and are not in this list.");
    expect(empty).not.toHaveTextContent("Next: export the knowledge base");
  });
  it("export open: Next is export", async () => {
    await mountVerify(0, (f) => (f.counts = counts({ in_scope: 5, auto_approved: 5 }))).catch(() => undefined);
    const empty = await screen.findByTestId("queue-empty");

    expect(await within(empty).findByTestId("queue-next")).toHaveTextContent("Next: export the knowledge base.");
  });
});

describe("M12 e2e finding: a figure flag raised before the block's detail arrives", () => {
  it("still targets the figure (design 09 O6), by loading the detail first", async () => {
    const { f, r } = await mountVerify(2, (fk) => {
      fk.items = [makeQueueItem(1, { type: "figure" }), makeQueueItem(2)];
      const d = makeBlockDetail(fk.items[0]);
      server.use(
        http.get("*/api/verify/blocks/:id", async ({ params }) => {
          await delay(400);
          return HttpResponse.json(String(params.id) === d.block.id ? d : makeBlockDetail(fk.items[1]));
        }),
      );
    });
    await r.user.keyboard("f");
    await screen.findByRole("dialog", { name: "Flag block" });
    await r.user.keyboard("4{Enter}");
    await waitFor(() => expect(f.actions).toHaveLength(1), { timeout: 3000 });
    expect(f.actions[0]).toMatchObject({ kind: "flag", block_id: vid(1), flag: { category: "bad_crop", target_id: "FIG-doc-p001-01" } });
  });
});
