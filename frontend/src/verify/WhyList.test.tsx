import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WhyItem } from "../api/schema";
import WhyList from "./WhyList";

const sig = (name: string, value: number | null, detail: string | null = null, critical = false): WhyItem => ({ kind: "signal", name, value, critical, detail });
const rows = () => within(screen.getByLabelText("Why this needs you, signals")).getAllByRole("listitem");
const row = (name: RegExp) => rows().find((r) => name.test(r.textContent ?? ""))!;

describe("WhyList: faithfulness outcomes come from the block's check, not from the number", () => {
  it("0.0 with faithfulness.passed false is the only red row: Failed, Cleanup changed words", () => {
    render(<WhyList why={[sig("faithfulness", 0, "1 violation: numeric mismatch '0.25' -> '0.52'", true)]} autoApproved={null} faithfulnessPassed={false} />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "failed");
    expect(r).toHaveTextContent("Failed");
    expect(r).toHaveTextContent("Cleanup changed words");
  });
  it("0.5 on a passed check (model cleanup rejected) is a held marigold row with the sentence from the detail, never Failed", () => {
    render(<WhyList why={[sig("faithfulness", 0.5, "cleanup candidate rejected (numeric); kept deterministic result", true)]} autoApproved={null} faithfulnessPassed />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "held");
    expect(r).not.toHaveTextContent("Failed");
    expect(r).toHaveTextContent("A model's cleanup was rejected; the deterministic cleanup was kept");
    expect(r).toHaveTextContent("0.50 of 1");
    expect(r.className).toContain("border-needs-line");
  });
  it("0.9 on a passed check (evidence-backed reorder) is held with its own sentence", () => {
    render(<WhyList why={[sig("faithfulness", 0.9, "passed via evidence-backed reorder", true)]} autoApproved={null} faithfulnessPassed />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "held");
    expect(r).toHaveTextContent("Passed after a reading-order fix backed by the page");
    expect(r).not.toHaveTextContent("Failed");
  });
  it("1.0 passed: a quiet Passed row; the technical line names the check neutrally and drops 'can hold a block on its own'", () => {
    render(<WhyList why={[sig("faithfulness", 1, "passed", true)]} autoApproved={null} faithfulnessPassed />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "passed");
    expect(r).toHaveTextContent("Cleanup kept every word");
    expect(r).not.toHaveTextContent("can hold a block on its own");
    expect(r).toHaveTextContent(/critical check/);
    expect(r).toHaveTextContent('Looked for "cleanup changed content", found nothing');
  });
  it("1.0 with 'raw (no cleanup yet)' reads 'Cleanup has not run yet', not 'Cleanup kept every word'", () => {
    render(<WhyList why={[sig("faithfulness", 1, "raw (no cleanup yet)", true)]} autoApproved={null} faithfulnessPassed />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "not_run");
    expect(r).toHaveTextContent("Cleanup has not run yet");
    expect(r).not.toHaveTextContent("Cleanup kept every word");
  });
  it("a signal without a value is 'Not measured' with its short name, never the passed sentence", () => {
    render(<WhyList why={[sig("llm_verifier", null, null)]} autoApproved={null} />);
    const r = rows()[0];
    expect(r).toHaveAttribute("data-outcome", "not_run");
    expect(r).toHaveTextContent("Not measured");
    expect(r).toHaveTextContent("verifier disagrees");
    expect(r).not.toHaveTextContent("A second model reads it the same");
  });
});

describe("WhyList: the heading line and auto-approved blocks", () => {
  it("counts the checks that found something, in plain words", () => {
    render(<WhyList why={[sig("parser_agreement", 0.6, "pymupdf vs docling 0.6", true), sig("reading_order_risk", 0.97), sig("garbage_ratio", 1)]} autoApproved={null} />);
    expect(screen.getByText(/2 checks found something to look at/)).toBeInTheDocument();
    expect(screen.queryByText(/held this block/)).toBeNull();
  });
  it("on an auto-approved block, signals under 1 are neutral rows, not marigold cards", () => {
    render(<WhyList why={[sig("reading_order_risk", 0.97, "x"), sig("garbage_ratio", 1)]} autoApproved={{ confidence: 0.93, threshold: 0.85 }} />);
    expect(screen.getByText(/The checks cleared this block/)).toBeInTheDocument();
    const r = row(/reading order/);
    expect(r).toHaveAttribute("data-outcome", "noted");
    expect(r.className).not.toContain("border-needs-line");
    expect(r.querySelector("svg")).toBeNull();
  });
});

describe("WhyList: each reading signal shows its own pair of readings", () => {
  const texts = { pymupdf: "Set to 0.25 mm\nTorque 35 N·m", docling: "Set to 0.25 mm\nTorque 35 N·m", ocr: "Set to 0.25 mm\nTorque 36 N·m", ocr_alt: "Set to O.25 mm\nTorque 36 N·m" };
  it("textlayer_vs_ocr compares the text layer with OCR, not the two text-layer parsers", () => {
    render(<WhyList why={[sig("textlayer_vs_ocr", 0.8, "text layer vs OCR 0.8")]} autoApproved={null} parserTexts={texts} rawSource="pymupdf" />);
    const cmp = screen.getByTestId("parser-compare");
    expect(cmp).toHaveTextContent("PDF text layer");
    expect(cmp).toHaveTextContent("OCR");
    expect(cmp).not.toHaveTextContent("Layout parser");
    expect(cmp).toHaveTextContent("36");
  });
  it("parser_agreement uses the pair its detail names (ocr vs ocr_alt on a scan)", () => {
    render(<WhyList why={[sig("parser_agreement", 0.5, "ocr vs ocr_alt 0.5", true)]} autoApproved={null} parserTexts={{ ocr: texts.ocr, ocr_alt: texts.ocr_alt }} />);
    const cmp = screen.getByTestId("parser-compare");
    expect(cmp).toHaveTextContent("Second OCR");
    expect(cmp).toHaveTextContent("O.25");
  });
  it("a pair that agrees line for line says so instead of showing nothing", () => {
    render(<WhyList why={[sig("parser_agreement", 0.9, "pymupdf vs docling 0.9")]} autoApproved={null} parserTexts={texts} />);
    expect(screen.queryByTestId("parser-compare")).toBeNull();
    expect(screen.getByTestId("readings-agree")).toHaveTextContent("The two readings agree line for line; the difference is elsewhere");
  });
});
