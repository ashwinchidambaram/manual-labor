import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ActionBar from "./ActionBar";

const noop = (): void => undefined;
const bar = (saveState: string) => (
  <ActionBar hasCurrent isFigure={false} position="Block 3 of 216" saveState={saveState} onApprove={noop} onEdit={noop} onFlag={noop} onSkip={noop} onBack={noop} onHelp={noop} />
);

describe("ActionBar save promise (review M13 P2-19)", () => {
  it("says 'saved after every action' only while saves go through", () => {
    const r = render(bar("Saved"));
    expect(screen.getByRole("toolbar")).toHaveTextContent("Block 3 of 216 · saved after every action");
    r.rerender(bar("Not saved"));
    expect(screen.getByRole("toolbar")).not.toHaveTextContent("saved after every action");
    expect(screen.getByRole("toolbar")).toHaveTextContent("not saved: your last action did not reach the server");
  });
});
