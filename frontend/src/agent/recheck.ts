// A proposal's re-checks in a reviewer's words (design 09 section 14). The server reports each check by its code name
// (manuallabor/agent/recheck.py, REQUIRED_CHECKS in manuallabor/contracts/proposal.py) with a note in plain words;
// the card shows the sentence for the outcome first and the note under it. An unknown name is shown as it is.

export const RECHECK_WORDS: Record<string, { passed: string; failed: string }> = {
  shape: { passed: "The answer has the expected form", failed: "The answer is not in the expected form" },
  changed: { passed: "It changes something", failed: "It changes nothing" },
  evidence: { passed: "The passages the model quoted are in their source", failed: "The passages the model quoted are not in their source" },
  faithfulness: { passed: "It adds no words that are not in the manual", failed: "It adds or changes words that are not in the manual" },
  numeric_attested: {
    passed: "Every changed number is shown by another reading of the page",
    failed: "A changed number is not shown by another reading of the page",
  },
  token_whitespace: { passed: "No new word that the page does not show", failed: "It has words that no reading of the page shows" },
  garbage_ratio: { passed: "No more garbled characters than before", failed: "More garbled characters than before" },
  parser_agreement: { passed: "As close to the other readings of the page as before", failed: "Further from the other readings of the page" },
  table_coverage: { passed: "The table keeps all the text of the page", failed: "The table leaves out text that is on the page" },
  table_position: { passed: "Each cell sits where the page has it", failed: "Some cells are not where the page has them" },
  table_consistency: { passed: "The table's rows and columns line up", failed: "The table's rows or columns do not line up" },
  attach_target: { passed: "The figure and the article can be joined", failed: "The figure cannot go into that article" },
  attach_evidence: { passed: "The article refers to the figure or sits next to it", failed: "Nothing in the article points to this figure" },
  regroup_target: { passed: "The topic it moves to exists", failed: "The block cannot move to that topic" },
  regroup_similarity: { passed: "The block reads like the topic it moves to", failed: "The block does not read like the topic it moves to" },
  bbox_geometry: { passed: "The new crop has a sensible size and stays on the page", failed: "The new crop is too small, too big or off the page" },
  bbox_text_overlap: { passed: "The new crop covers no body text", failed: "The new crop covers body text" },
  bbox_content: { passed: "The new crop has something drawn in it", failed: "The new crop is almost empty" },
};

export function recheckSentence(check: string, passed: boolean): string {
  const w = RECHECK_WORDS[check];
  return w ? (passed ? w.passed : w.failed) : check.replace(/_/g, " ");
}
