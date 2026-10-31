// Plain words at decision points (design 09 section 14, second first-use report C5): every re-check the server can
// report (manuallabor/contracts/proposal.py REQUIRED_CHECKS) reads as a sentence a reviewer would say, never its code
// name; the scorer's jargon on the why list is translated; the flag sentence has no command line in it.
import { describe, expect, it } from "vitest";
import { FLAG_RESOLUTION, plainDetail } from "../verify/labels";
import { recheckSentence, RECHECK_WORDS } from "./recheck";

const REQUIRED = [
  "shape", "changed", "evidence", "faithfulness", "numeric_attested", "token_whitespace", "garbage_ratio", "parser_agreement",
  "table_coverage", "table_position", "table_consistency", "attach_target", "attach_evidence", "regroup_target",
  "regroup_similarity", "bbox_geometry", "bbox_text_overlap", "bbox_content",
];
const JARGON = /attest|token|garbage|symbol soup|whitespace|bbox|regroup|_/i;

describe("re-check sentences", () => {
  it("every check the server requires has a passed and a failed sentence in plain words", () => {
    for (const c of REQUIRED) {
      expect(RECHECK_WORDS[c], c).toBeDefined();
      for (const passed of [true, false]) {
        const s = recheckSentence(c, passed);
        expect(s, `${c} ${passed}`).not.toMatch(JARGON);
        expect(s.length).toBeGreaterThan(10);
      }
    }
  });
  it("the checks Dana read", () => {
    expect(recheckSentence("numeric_attested", false)).toBe("A changed number is not shown by another reading of the page");
    expect(recheckSentence("faithfulness", false)).toBe("It adds or changes words that are not in the manual");
    expect(recheckSentence("token_whitespace", true)).toBe("No new word that the page does not show");
    expect(recheckSentence("garbage_ratio", true)).toBe("No more garbled characters than before");
  });
  it("an unknown check is shown by its name, never hidden", () => {
    expect(recheckSentence("brand_new_check", false)).toBe("brand new check");
  });
});

describe("the scorer's words on the why list", () => {
  it("translates symbol soup and reader keys, keeping the numbers", () => {
    expect(plainDetail("garbage_ratio", "0/32 tokens symbol soup")).toBe("0 of 32 words garbled");
    expect(plainDetail("garbage_ratio", "3/12 tokens symbol soup ('#@!'); fragmentation 0.40")).toBe("3 of 12 words garbled ('#@!'); words split into single letters 0.40");
    expect(plainDetail("parser_agreement", "pymupdf vs docling 1")).toBe("PDF text layer vs Layout parser: 1");
    expect(plainDetail("parser_agreement", "ocr vs ocr_alt 0.5; numeric: '-' vs '·'")).toBe("OCR vs Second OCR: 0.5; numbers differ: '-' vs '·'");
  });
  it("leaves every other detail as the scorer wrote it", () => {
    expect(plainDetail("ocr_min", "min 0.923 at 'X200'; 4 words")).toBe("min 0.923 at 'X200'; 4 words");
    expect(plainDetail("parser_agreement", null)).toBeNull();
  });
});

describe("the flag sentence", () => {
  it("names no command line", () => {
    expect(FLAG_RESOLUTION).not.toMatch(/labor|--override|blanket|command/);
    expect(FLAG_RESOLUTION).toContain("An override of the block alone never covers a flag.");
  });
});
