import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeGroup } from "../test/fixtures";
import GroupRow, { type GroupRowProps } from "./GroupRow";

const props = (over: Partial<GroupRowProps> = {}): GroupRowProps => ({
  group: makeGroup({ id: "g-a-t001", doc_id: "a", view: "topic", title: "Coolant", block_ids: ["b1", "b2"], cohesion: 0.41, block_count: 2 }),
  view: "topic",
  depth: 1,
  posInSet: 1,
  setSize: 1,
  hasChildren: false,
  childCount: 0,
  expanded: false,
  check: "checked",
  fraction: 1,
  stale: false,
  low: false,
  cursor: true,
  onToggle: () => undefined,
  onExpand: () => undefined,
  onCursor: () => undefined,
  ...over,
});

describe("GroupRow copy (review M13 P2-15, P2-21)", () => {
  it("a topic row without the Mixed subjects chip shows no bare cohesion number", () => {
    render(<GroupRow {...props()} />);
    expect(screen.getByTestId("row-meta")).not.toHaveTextContent(/cohesion/);
    expect(screen.getByTestId("row")).not.toHaveTextContent("0.41");
  });
  it("the Mixed subjects chip keeps the number in its accessible name", () => {
    render(<GroupRow {...props({ low: true })} />);
    expect(screen.getByTestId("low-cohesion")).toHaveAttribute("aria-label", "Mixed subjects, cohesion 0.41");
  });
  it("an empty Unassigned row says 'empty', not 'n/a selected'", () => {
    const g = makeGroup({ id: "g-a-un", doc_id: "a", view: "topic", title: "Unassigned", block_ids: [], is_unassigned: true, block_count: 0 });
    render(<GroupRow {...props({ group: g, fraction: null, check: "unchecked" })} />);
    const chip = screen.getByTestId("coverage-chip");
    expect(chip).toHaveTextContent(/^empty$/);
    expect(chip).toHaveAttribute("aria-label", "this topic has no blocks");
  });
});
