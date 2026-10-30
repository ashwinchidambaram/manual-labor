import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Block, WhyItem } from "../api/schema";
import PageStrip from "./PageStrip";
import { pageMarks, stripRegion } from "./pageMarks";

const page = { doc_id: "doc", page: 3, width: 612, height: 792, render_url: "/api/docs/doc/pages/3.png", source_url: "/api/docs/doc/source" };
const block = (over: Partial<Block> = {}): Block =>
  ({
    id: "b-doc-p003-01",
    doc_id: "doc",
    page: 3,
    bbox: [72, 100, 372, 140],
    raw_text_by_parser: {},
    ocr_words: [],
    ...over,
  }) as unknown as Block;
const word = (text: string, x: number, confidence = 0.99) => ({ text, bbox: [x, 100, x + 30, 112] as [number, number, number, number], confidence });
const ocrMin = (value: number): WhyItem => ({ kind: "signal", name: "ocr_min", value, critical: false, detail: "min 0.41 at 'M8'; 3 words" });

describe("pageMarks", () => {
  it("no block: nothing to mark", () => {
    expect(pageMarks(null)).toEqual({ boxes: [], whole: false, weakest: null });
  });
  it("the words where the two readings differ are boxed on the OCR words they map to", () => {
    const b = block({ raw_text_by_parser: { pymupdf: "Set to 0.25 mm", docling: "Set to 0.52 mm" }, ocr_words: [word("Set", 72), word("to", 110), word("0.25", 140), word("mm", 180)] });
    expect(pageMarks(b).boxes).toEqual([[140, 100, 170, 112]]);
    expect(pageMarks(b).whole).toBe(false);
  });
  it("readings that differ where no OCR word matches hatch the whole block", () => {
    const b = block({ raw_text_by_parser: { pymupdf: "alpha", docling: "beta" }, ocr_words: [] });
    expect(pageMarks(b)).toMatchObject({ boxes: [], whole: true });
  });
  it("identical readings mark nothing", () => {
    expect(pageMarks(block({ raw_text_by_parser: { pymupdf: "same", docling: "same" } }))).toEqual({ boxes: [], whole: false, weakest: null });
  });
  it("the least certain word is outlined only when the OCR signal held the block", () => {
    const b = block({ ocr_words: [word("Set", 72, 0.98), word("M8", 110, 0.41), word("bolt", 150, 0.9)] });
    expect(pageMarks(b, [ocrMin(0.41)]).weakest).toEqual([110, 100, 140, 112]);
    expect(pageMarks(b, [ocrMin(1)]).weakest).toBeNull();
    expect(pageMarks(b, []).weakest).toBeNull();
  });
  it("stripRegion adds a margin and stays inside the page", () => {
    expect(stripRegion([72, 100, 372, 140], page)).toEqual([64, 97, 380, 143]);
    expect(stripRegion([2, 1, 610, 791], page)).toEqual([0, 0, 612, 792]);
  });
});

describe("PageStrip", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 632, height: 100, top: 0, left: 0, right: 632, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
  });
  afterEach(() => vi.restoreAllMocks());
  it("magnifies the block's region to the strip's width, with the page image at the 150 dpi render", () => {
    render(<PageStrip page={page} bbox={[72, 100, 372, 140]} marks={{ boxes: [], whole: false, weakest: null }} pageNo={3} />);
    const img = screen.getByTestId("page-strip").querySelector("img")!;
    expect(img.getAttribute("src")).toBe("/api/docs/doc/pages/3.png?dpi=150");
    // region 64..380 (316pt) fitted to 632px: 2x; the whole page is then 1224px wide, under the 1700px cap
    expect(img.style.width).toBe("1224px");
    expect(img.style.left).toBe("-128px");
    expect(screen.getByRole("img", { name: "Page 3, magnified to this block" })).toBeInTheDocument();
    expect(screen.queryByText("where the readings differ")).toBeNull();
  });
  it("never draws a page wider than the cap, however narrow the block", () => {
    render(<PageStrip page={page} bbox={[100, 100, 110, 110]} marks={{ boxes: [], whole: false, weakest: null }} pageNo={3} />);
    expect(screen.getByTestId("page-strip").querySelector("img")!.style.width).toBe("1700px");
  });
  it("marks and their legend: shaded where the readings differ, dashed around the least certain word", () => {
    render(<PageStrip page={page} bbox={[72, 100, 372, 140]} marks={{ boxes: [[140, 100, 170, 112]], whole: false, weakest: [110, 100, 140, 112] }} pageNo={3} />);
    expect(screen.getAllByTestId("strip-disagree-word")).toHaveLength(1);
    expect(screen.getByTestId("strip-weakest")).toBeInTheDocument();
    expect(screen.getByText("where the readings differ")).toBeInTheDocument();
    expect(screen.getByText("least certain word")).toBeInTheDocument();
  });
  it("a whole-block disagreement is hatched", () => {
    render(<PageStrip page={page} bbox={[72, 100, 372, 140]} marks={{ boxes: [], whole: true, weakest: null }} pageNo={3} />);
    expect(screen.getByTestId("strip-disagree-block")).toBeInTheDocument();
  });
});
