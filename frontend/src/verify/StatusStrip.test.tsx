import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { counts } from "../test/verifyFake";
import { scopeTerms } from "../shell/scopeTerms";
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

// design 11 section 17: the strip shows the gate's partition only when it describes the same moment as the list below
describe("StatusStrip: the gate's partition or the list's own counts", () => {
  const gate = (over: Record<string, number> = {}) =>
    scopeTerms({
      unlocked: false,
      open_flags: 1,
      queued: 4,
      overrides: [],
      counts: { in_scope: 10, auto_approved: 3, approved: 1, edited: 0, rejected: 1, overridden: 2, blocking: 3, to_review: 2, flagged: 1, ...over },
    });
  it("names overridden blocks apart from those waiting when the two reads agree", () => {
    render(<StatusStrip {...props({ scope: gate() })} />);
    expect(screen.getByTestId("cnt-queued")).toHaveTextContent("2");
    expect(screen.getByTestId("cnt-overridden")).toHaveTextContent("2");
    expect(screen.getByTestId("reconcile-review")).toHaveTextContent("In scope 10 = 2 to review + 2 overridden + 3 auto-approved + 1 done + 1 flagged + 1 rejected");
  });
  it("an older gate read (one approve behind the list): the list's buckets, its overrides still apart from those waiting", () => {
    // the list already counts the approve (done 1 -> 2, queued 4 -> 3); the gate does not yet
    const newer = counts({ in_scope: 10, auto_approved: 3, approved: 2, flagged_open: 1, rejected: 1, pending: 3 });
    render(<StatusStrip {...props({ counts: newer, scope: gate() })} />);
    expect(screen.getByTestId("cnt-done")).toHaveTextContent("2");
    expect(screen.getByTestId("cnt-overridden")).toHaveTextContent("2");
    expect(screen.getByTestId("reconcile-review")).toHaveTextContent("In scope 10 = 1 to review + 2 overridden + 3 auto-approved + 2 done + 1 flagged + 1 rejected");
  });
  it("a gate read of another scope (a manual scored between the reads): the list's own counts only", () => {
    render(<StatusStrip {...props({ scope: gate({ in_scope: 70, auto_approved: 63 }) })} />);
    expect(screen.queryByTestId("cnt-overridden")).toBeNull();
    expect(screen.getByTestId("reconcile-review")).toHaveTextContent("In scope 10 = 4 to review + 3 auto-approved + 1 done + 1 flagged + 1 rejected");
  });
});
