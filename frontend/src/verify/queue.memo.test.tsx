// QueueCard is memoised: re-rendering the queue with the same items must not re-render its cards.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { counts, makeQueueItem, ready } from "../test/verifyFake";

const calls = vi.hoisted(() => ({ n: 0 }));
vi.mock("./reasons", async (orig) => {
  const m = await orig<typeof import("./reasons")>();
  return { ...m, reasonChips: ((...a: Parameters<typeof m.reasonChips>) => ((calls.n += 1), m.reasonChips(...a))) as typeof m.reasonChips };
});

import Queue from "./Queue";

describe("QueueCard memo", () => {
  it("M7 does not re-render unchanged cards when the parent re-renders", () => {
    const items = Array.from({ length: 8 }, (_, i) => makeQueueItem(i + 1));
    const wantFocus = { current: false };
    const noop = (): void => undefined;
    const docs = [ready("doc")];
    const c = counts();
    const ui = (pinned: typeof items[number] | null) => (
      <MemoryRouter>
        <Queue items={items} total={8} pinned={pinned} currentId={items[0].block_id} docs={docs} counts={c} focusTick={0} wantFocus={wantFocus} onSelect={noop} onNearEnd={noop} threshold={0.85} />
      </MemoryRouter>
    );
    const r = render(ui(null));
    const first = calls.n;
    expect(first).toBeGreaterThan(0);
    r.rerender(ui(null));
    r.rerender(ui(null));
    expect(calls.n).toBe(first);
  });
});
