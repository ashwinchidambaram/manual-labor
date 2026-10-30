import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeBlockDetail, makeQueueItem, makeRailItem } from "../test/verifyFake";
import ChecksList, { checkRows } from "./ChecksList";

const block = (over: Parameters<typeof makeBlockDetail>[2] = {}) => makeBlockDetail(makeQueueItem(1), {}, over).block;
const viol = (kind: "insertion" | "deletion" | "numeric_mismatch" | "reorder", raw: string, clean: string) => ({ kind, raw, clean, raw_start: 0, raw_end: 1, clean_start: 0, clean_end: 1 });

describe("U9 ChecksList", () => {
  it("passing faithfulness: Passed rows with the alignment as a percentage", () => {
    render(<ChecksList block={block({ faithfulness: { passed: true, alignment_ratio: 0.984, violations: [], diff: [], numeric_variants: [] } })} />);
    const f = screen.getByTestId("check-faithfulness");
    expect(f).toHaveAttribute("data-outcome", "passed");
    expect(f).toHaveTextContent("Passed");
    expect(f).toHaveTextContent("98% of the text aligns");
    expect(screen.getByTestId("check-numbers")).toHaveTextContent(/Numbers preserved.?Passed/);
  });
  it("a numeric mismatch fails both faithfulness and Numbers preserved, with the kinds counted", () => {
    render(
      <ChecksList
        block={block({
          faithfulness: { passed: false, alignment_ratio: 0.9, violations: [viol("numeric_mismatch", "0.25", "0.52"), viol("insertion", "", "x")], diff: [], numeric_variants: [] },
        })}
      />,
    );
    expect(screen.getByTestId("check-faithfulness")).toHaveTextContent("Failed");
    expect(screen.getByTestId("check-faithfulness")).toHaveTextContent("2 violations: 1 numeric mismatch, 1 insertion");
    const n = screen.getByTestId("check-numbers");
    expect(n).toHaveTextContent("Numbers preserved");
    expect(n).toHaveTextContent("Failed");
    expect(n).toHaveTextContent("0.25 became 0.52");
  });
  it("missing data is 'Not run yet', never 'Passed'", () => {
    render(<ChecksList block={block({ faithfulness: null, signals: [] })} />);
    for (const id of ["faithfulness", "numbers", "parsers"]) {
      const row = screen.getByTestId(`check-${id}`);
      expect(row).toHaveAttribute("data-outcome", "not_run");
      expect(row).toHaveTextContent("Not run yet");
      expect(row).not.toHaveTextContent("Passed");
    }
  });
  it("agreement signals are shown as measured values with the scorer's detail, never as a verdict", () => {
    const rows = checkRows(
      block({
        signals: [
          { name: "parser_agreement", value: 0.93, critical: true, detail: "pymupdf vs docling 0.93" },
          { name: "textlayer_vs_ocr", value: 1, critical: false, detail: null },
          { name: "ocr_min", value: 0.41, critical: false, detail: "weakest word 'M8'" },
        ],
      }),
    );
    const by = new Map(rows.map((r) => [r.id, r]));
    expect(by.get("parsers")).toMatchObject({ outcome: "measured", result: "Differ (0.93)", detail: "Critical for this block. pymupdf vs docling 0.93" });
    expect(by.get("textlayer")).toMatchObject({ outcome: "measured", result: "Match (1.00)" });
    expect(by.get("ocr_min")).toMatchObject({ result: "0.41" });
  });
  it("a DOCX-like block without OCR has no text-layer row; scored without a parser pair says so", () => {
    const rows = checkRows(block({ signals: [{ name: "ocr_mean", value: 0.9, critical: false, detail: null }] }));
    expect(rows.find((r) => r.id === "textlayer")).toBeUndefined();
    expect(rows.find((r) => r.id === "parsers")).toMatchObject({ outcome: "not_run", result: "Not measured for this block" });
  });
  it("figure blocks show the extraction method and the attach rule from the rail item", () => {
    const item = makeQueueItem(2, { type: "figure" });
    const b = makeBlockDetail(item).block;
    const rail = makeRailItem("FIG-doc-p001-01", b.id);
    render(<ChecksList block={b} figure={rail} />);
    const list = screen.getByTestId("checks-list");
    expect(within(list).queryByTestId("check-faithfulness")).toBeNull();
    expect(within(list).getByTestId("check-method")).toHaveTextContent(rail.record.extraction);
    expect(within(list).getByTestId("check-attach")).toHaveTextContent(rail.attachment?.rule ?? "unattached");
  });
});
