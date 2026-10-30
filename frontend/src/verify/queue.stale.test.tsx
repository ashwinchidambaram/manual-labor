// A queue page the server answered before an approve was processed must not be applied after it: it lists the
// approved block as queued and names it as the current block, and the screen would go back to the block the reviewer
// just approved (seen as a flaky "approve did not advance" in UX2 while scoring refetches every 3 s).
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/server";
import { counts, cursor, ready, vid, type VerifyFake } from "../test/verifyFake";
import { card, cardFocused, mountVerify } from "./helpers.test-util";

const stalePage = (f: VerifyFake) => ({
  items: f.items.map((i) => ({ ...i })),
  total: f.items.length,
  counts: { ...counts({ in_scope: f.items.length }), pending: f.items.length },
  docs: f.docs,
  cursor: cursor({ current_block_id: vid(1) }),
});

describe("stale queue snapshots", () => {
  it("a refetch that left before an approve settled is fetched again, not applied: the screen stays on the next block", async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => (release = res));
    let held = 0;
    let after = 0;
    const { f, r } = await mountVerify(4, (fk) => {
      // a document still scoring keeps the queue refetching (every 3 s)
      fk.docs = [ready("doc"), { doc_id: "late", state: "pending", stale: false, waiting_for: "score2" }];
    });
    server.use(
      http.get("*/api/verify/queue", async () => {
        if (held === 0) {
          held = 1;
          const page = stalePage(f); // the server's answer at this moment: block 1 still queued and current
          await gate;
          return HttpResponse.json(page);
        }
        after += 1;
        return undefined; // later requests: the live fake
      }),
    );
    await waitFor(() => expect(held).toBe(1), { timeout: 6000 });
    await r.user.keyboard("a");
    await waitFor(() => expect(f.actions.map((a) => a.block_id)).toEqual([vid(1)]));
    await cardFocused(vid(2));
    // the approve and its cursor PUT have settled; now the old answer arrives
    await new Promise((res) => setTimeout(res, 600));
    release();
    await new Promise((res) => setTimeout(res, 500));
    expect(card(vid(2))).toHaveAttribute("aria-current", "true");
    expect(document.querySelector(`[data-testid='card-${vid(1)}']`)).toBeNull();
    // and the stale answer was replaced by a fresh one at once, not at the next 3 s poll
    await waitFor(() => expect(after).toBeGreaterThan(0), { timeout: 1500 });
  }, 20000);
});
