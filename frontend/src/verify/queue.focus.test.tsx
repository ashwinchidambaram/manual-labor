// The focused queue card keeps focus when its row moves (a refetch during scoring inserts rows ahead of it) and when
// the pinned copy hands over to the list card. Focus must never fall to <body> (review M13 P1-4).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { QueueItem } from "../api/schema";
import { counts, makeQueueItem, ready } from "../test/verifyFake";
import Queue from "./Queue";

const noop = (): void => undefined;
const ui = (items: QueueItem[], currentId: string, pinned: QueueItem | null, wantFocus: { current: boolean }, tick = 0) => (
  <MemoryRouter>
    <Queue
      items={items}
      total={items.length + (pinned ? 1 : 0)}
      pinned={pinned}
      currentId={currentId}
      docs={[ready("doc")]}
      counts={counts()}
      focusTick={tick}
      wantFocus={wantFocus}
      onSelect={noop}
      onNearEnd={noop}
      threshold={0.85}
    />
  </MemoryRouter>
);

describe("queue focus survives virtualisation", () => {
  it("40 rows inserted ahead of the focused card: focus stays on the current card", () => {
    const items = Array.from({ length: 20 }, (_, i) => makeQueueItem(i + 1));
    const cur = items[0].block_id;
    const wantFocus = { current: true };
    const r = render(ui(items, cur, null, wantFocus, 1));
    expect(document.activeElement).toBe(screen.getByTestId(`card-${cur}`));
    const ahead = Array.from({ length: 40 }, (_, i) => makeQueueItem(100 + i));
    r.rerender(ui([...ahead, ...items], cur, null, wantFocus, 1));
    expect(document.activeElement).toBe(screen.getByTestId(`card-${cur}`));
  });
  it("a pinned current card that comes back in the list hands focus to its list card", () => {
    const items = Array.from({ length: 5 }, (_, i) => makeQueueItem(i + 1));
    const extra = makeQueueItem(50);
    const wantFocus = { current: true };
    const r = render(ui(items, extra.block_id, extra, wantFocus, 1));
    const pinnedCard = screen.getByTestId(`card-${extra.block_id}`);
    expect(pinnedCard).toHaveAttribute("data-pinned", "true");
    expect(document.activeElement).toBe(pinnedCard);
    r.rerender(ui([...items.slice(0, 2), extra, ...items.slice(2)], extra.block_id, null, wantFocus, 1));
    const listCard = screen.getByTestId(`card-${extra.block_id}`);
    expect(listCard).not.toHaveAttribute("data-pinned");
    expect(document.activeElement).toBe(listCard);
  });
  it("focusing the current card never scrolls the page (the queue scrolls its own list)", () => {
    const spy = vi.spyOn(HTMLElement.prototype, "focus");
    const items = Array.from({ length: 3 }, (_, i) => makeQueueItem(i + 1));
    render(ui(items, items[1].block_id, null, { current: true }, 1));
    expect(spy).toHaveBeenCalledWith({ preventScroll: true });
    spy.mockRestore();
  });
});
