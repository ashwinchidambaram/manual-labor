import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { counts } from "../test/verifyFake";
import StatusStrip, { type StatusStripProps } from "./StatusStrip";

const props = (over: Partial<StatusStripProps> = {}): StatusStripProps => ({
  counts: counts({ in_scope: 10, auto_approved: 3, approved: 1, flagged_open: 1, rejected: 1, pending: 4 }),
  viewAdded: 0,
  viewAddedPartial: false,
  appliedView: null,
  docs: [],
  threshold: 0.85,
  view: null,
  sort: "worst_first",
  onView: () => undefined,
  onSort: () => undefined,
  saveState: "Saved",
  ...over,
});
const bar = () => screen.getByTestId("review-bar");
const segments = () => Array.from(bar().children) as HTMLElement[];
const scaleOf = (el: HTMLElement) => Number(/scaleX\(([\d.]+)\)/.exec(el.style.transform)?.[1] ?? NaN);

describe("StatusStrip: the progress bar is drawn from the server's own counts", () => {
  it("draws the waiting segment from counts.queued, not from what is left over", () => {
    render(<StatusStrip {...props()} />);
    const segs = segments();
    expect(segs).toHaveLength(4);
    // done 1, auto 3, flagged+rejected 2, queued 4: in scope 10
    expect(segs.map(scaleOf)).toEqual([0.1, 0.3, 0.2, 0.4]);
    expect(segs[3].className).toContain("bg-needs-fill");
    expect(bar().className).not.toContain("bg-needs-fill");
  });
  it("names the flagged segment honestly when it also holds rejected blocks", () => {
    render(<StatusStrip {...props()} />);
    expect(bar()).toHaveAttribute("aria-label", expect.stringContaining("2 flagged or rejected"));
    expect(screen.getByTestId("cnt-flagged")).toHaveTextContent("1");
    expect(screen.getByTestId("cnt-rejected")).toHaveTextContent("1");
  });
  it("says only 'flagged' when nothing was rejected", () => {
    render(<StatusStrip {...props({ counts: counts({ in_scope: 10, auto_approved: 3, approved: 1, flagged_open: 2, pending: 4 }) })} />);
    expect(bar()).toHaveAttribute("aria-label", expect.stringContaining("2 flagged,"));
    expect(screen.queryByTestId("cnt-rejected")).toBeNull();
  });
  it("counts that do not reconcile: a grey bar with no segments, and the mismatch is said in words", () => {
    render(<StatusStrip {...props({ counts: counts({ in_scope: 10, auto_approved: 3, approved: 1, queued: 9, pending: 9 }) })} />);
    expect(segments()).toHaveLength(0);
    expect(bar()).toHaveAttribute("data-reconciled", "false");
    expect(bar()).toHaveAttribute("aria-label", expect.stringMatching(/do not add up/));
    expect(screen.getByTestId("reconcile-mismatch")).toBeInTheDocument();
  });
  it("the short-window summary repeats 'N of M checked by you' and a button opens the rest", () => {
    render(<StatusStrip {...props()} />);
    expect(screen.getByTestId("review-summary")).toHaveTextContent("1 of 7 checked by you");
    const btn = screen.getByRole("button", { name: "Counts and filters" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(within(document.getElementById("review-details")!).getByTestId("cnt-done")).toBeInTheDocument();
  });
});
