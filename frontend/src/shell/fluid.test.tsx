// Fluid layout (design 13 section 9): the parts of it that are React, not CSS. Which parent holds the whole page from
// `vast`, the Scope dock's numbers below `wide`, Export's second column only when it has something to hold. The
// arrangement by size is measured in e2e/responsive.spec.ts.
import { renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExportStatus } from "../api/schema";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { mountVerify } from "../verify/helpers.test-util";
import { useMediaQuery, VAST_QUERY } from "./useMediaQuery";

/** A window whose width matches only the queries in `matches`. */
function mockMatchMedia(matches: string[]): void {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: matches.includes(q),
    media: q,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}
afterEach(() => vi.unstubAllGlobals());

describe("FL1 useMediaQuery", () => {
  it("is false where matchMedia is missing, and follows it where present", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(renderHook(() => useMediaQuery(VAST_QUERY)).result.current).toBe(false);
    mockMatchMedia([VAST_QUERY]);
    expect(renderHook(() => useMediaQuery(VAST_QUERY)).result.current).toBe(true);
  });
});

describe("FL2 Verify's whole page from vast", () => {
  it("below vast the page is the small locator in the band; there is no page column", async () => {
    mockMatchMedia([]);
    await mountVerify(3);
    await screen.findByTestId("page-strip");
    expect(screen.queryByTestId("page-column")).toBeNull();
    expect(within(screen.getByTestId("page-band")).getByRole("region", { name: "Source page" })).toBeInTheDocument();
  });

  it("from vast the page has its own column, drawn once, and the band says where it went", async () => {
    mockMatchMedia([VAST_QUERY]);
    await mountVerify(3);
    const col = await screen.findByTestId("page-column");
    expect(within(col).getByRole("region", { name: "Source page" })).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Source page" })).toHaveLength(1);
    expect(screen.getByTestId("page-band")).toHaveTextContent("The whole page is on the right.");
  });

  it("Z brings the page back into the band, zoomed, and the column goes", async () => {
    mockMatchMedia([VAST_QUERY]);
    const { r } = await mountVerify(3);
    await screen.findByTestId("page-column");
    await r.user.keyboard("z");
    await waitFor(() => expect(screen.queryByTestId("page-column")).toBeNull());
    expect(within(screen.getByTestId("page-band")).getByRole("region", { name: "Source page" })).toBeInTheDocument();
  });
});

describe("FL3 Scope dock", () => {
  it("repeats the summary's blocks and estimated review, never its own numbers", async () => {
    installFake();
    renderApp("/scope");
    await screen.findByTestId("sum-blocks");
    await waitFor(() => expect(screen.getByTestId("dock-blocks")).toHaveTextContent(screen.getByTestId("sum-blocks").textContent!));
    expect(screen.getByTestId("dock-queued")).toHaveTextContent(screen.getByTestId("sum-queued").textContent!);
    expect(screen.getByTestId("dock-counts")).toHaveTextContent(/blocks? · estimated review/);
  });
});

describe("FL4 Export columns", () => {
  const status = (over: Partial<ExportStatus>): ExportStatus => ({
    unlocked: false,
    open_flags: 0,
    queued: 2,
    blockers: ["b-doc-p001-01"],
    overrides: [],
    summary: null,
    zip_path: null,
    ...over,
  });
  it("locked: the gate in the main column, the override form in the side column", async () => {
    installFake({ exportStatus: status({}) });
    renderApp("/export");
    const main = await screen.findByTestId("export-main");
    expect(within(main).getByTestId("export-locked")).toBeInTheDocument();
    expect(within(screen.getByTestId("export-side")).getByTestId("override-form")).toBeInTheDocument();
  });
  it("ready with no overrides: no empty side column", async () => {
    installFake({ exportStatus: status({ unlocked: true, queued: 0, blockers: [] }) });
    renderApp("/export");
    await screen.findByTestId("export-ready");
    expect(screen.queryByTestId("export-side")).toBeNull();
  });
});
