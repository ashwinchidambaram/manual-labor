// How an agent item ended, in words a reviewer understands (design 09 section 11). The server's outcome codes and
// details are engineer talk ("proposal_text is missing"); the human sentence comes first, a code nobody mapped is
// shown as it is rather than hidden.
import type { AgentItemView } from "../api/schema";

/** Details the agent writes when a model answer cannot be used (manuallabor/agent/propose.py). */
const DETAIL: Record<string, string> = {
  "proposal_text is missing": "the model answered without the corrected text",
  "cells are missing": "the model answered without the table cells",
  "reply is not an object": "the model's answer was not in the expected form",
};

/** Outcomes recorded after a pass worked on the item; the rest are decided before a pass and are not attempts. */
export const RAN = new Set(["error", "no_proposal", "stale"]);

/** "error, the model answered without the corrected text" */
export function outcomeText(outcome: string, detail?: string | null): string {
  const d = detail?.trim() || null;
  switch (outcome) {
    case "error":
      return `error, ${d ? (DETAIL[d] ?? `the model call failed: ${d}`) : "no detail was recorded"}`;
    case "no_proposal":
      return d ? `the model proposed no change ("${d}")` : "the model proposed no change";
    case "stale":
      return "the manual changed while the agent ran";
    case "max_rounds":
      return `no rounds left${d ? ` (${d})` : ""}`;
    case "unsupported":
      return `the agent cannot work on this flag${d ? ` (${d})` : ""}`;
    case "stale_doc":
      return "the manual needs a re-run first";
    case "out_of_scope":
      return "the block is not in your selection";
    case "pending":
      return "a proposal is waiting";
    default:
      return d ? `${outcome} (${d})` : outcome;
  }
}

type Item = Pick<AgentItemView, "round" | "last_outcome" | "last_detail" | "pending_proposal_id"> & { attempts?: number | null };

/** How many passes worked on the item: the server's count, never fewer than its proposals or a recorded outcome. */
export function attemptsOf(it: Item): number {
  return Math.max(it.attempts ?? 0, it.round - 1, it.last_outcome && RAN.has(it.last_outcome) ? 1 : 0);
}

/**
 * How often the agent has tried this flag and how the last try ended. The server's `round` is the round the next pass
 * will run (proposals so far plus one); a pass that ends in an error leaves no proposal, so `attempts` counts passes.
 */
export function triedText(it: Item): string {
  const tried = attemptsOf(it);
  const last = it.last_outcome ? outcomeText(it.last_outcome, it.last_detail) : null;
  if (tried === 0 && !it.pending_proposal_id) return last ? `not tried: ${last}` : "not tried yet";
  const times = tried <= 1 ? "once" : `${tried} times`;
  return `tried ${times}${last ? `, last: ${last}` : ""}`;
}

/** The last try failed or proposed nothing: the reviewer is told how to get out (run again, or decide in Verify). */
export const stuck = (it: Item): boolean => it.last_outcome === "error" || it.last_outcome === "no_proposal" || it.last_outcome === "stale";
