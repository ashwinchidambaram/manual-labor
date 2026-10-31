// "Your next step" (design 13 section 2.5.1): one sentence that changes with state, shown at the top of the step
// rail. A screen may publish its own (Verify: what to look at on this block); otherwise the step's default is shown.
// Pure data in, so the copy is unit-tested and never says more than the server did.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ExportStatus } from "../api/schema";
import type { HotkeyId } from "../hotkeys";
import type { GuideControl } from "../onboarding/useGuideState";
import type { StepId } from "../onboarding/guide";
import { blockingFlagsOf, scopeTerms, toReviewOf } from "./scopeTerms";

export interface NextStep {
  /** the sentence; `{hotkeyId}` tokens render as keycaps */
  text: string;
  /** optional key legend under the sentence (Verify's decisions) */
  keys?: { id: HotkeyId; label: string }[];
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

/** What the shell knows beyond the gate: a job that reads or scores manuals is queued or running. */
export interface NextStepLive {
  scoring: boolean;
  reading?: boolean;
}

/**
 * The step's own next step, from the export gate's partition (design 11 section 17: "to review" is `to_review`, never
 * a block an override covers) and the active jobs (a block being scored is not waiting for anyone yet).
 */
export function defaultNextStep(step: StepId, st: ExportStatus | undefined, live: NextStepLive = { scoring: false }): NextStep {
  const queued = toReviewOf(st);
  const overridden = scopeTerms(st)?.overridden ?? 0;
  const flags = st?.open_flags ?? 0;
  const blockingFlags = blockingFlagsOf(st);
  switch (step) {
    case "scope":
      return {
        text: "Choose what goes into the knowledge base. Everything starts selected: {toggleRow} selects or clears a row, {selectAll} selects every block. {confirm} confirms: scoring starts and Verify opens at once.",
      };
    case "verify":
      if (live.scoring)
        return {
          text: live.reading
            ? "Your manuals are being read. Blocks come here once they are scored; confirm your scope on the Scope screen when reading finishes."
            : "Your selection is being scored. Blocks come here as each manual finishes scoring.",
        };
      if (queued > 0) return { text: `Check each block against its page. ${plural(queued, "block")} ${queued === 1 ? "waits" : "wait"} for you.` };
      if (overridden > 0)
        return {
          text: `Nothing waits for you. ${plural(overridden, "overridden block")} will be exported unreviewed; approving one here checks it after all.`,
        };
      return { text: "Check each block against its page." };
    case "agent":
      return flags > 0
        ? { text: `Run the agent pass on ${plural(flags, "open flag")}. Every proposal is checked again before you decide.` }
        : { text: "Nothing is flagged. In Verify, {vFlag} sends a block here when you would rather not fix it by hand." };
    case "export":
      if (!st) return { text: "Export the reviewed knowledge base." };
      if ((st.blockers ?? []).length === 0) return { text: "Export the knowledge base, then compare the zip's SHA-256 with the one shown." };
      return {
        text: [
          queued > 0 ? `${plural(queued, "block")} still ${queued === 1 ? "waits" : "wait"} for review.` : "",
          blockingFlags > 0 ? `${plural(blockingFlags, "open flag")} still ${blockingFlags === 1 ? "blocks" : "block"} the export.` : "",
          queued > 0 && blockingFlags > 0 ? "Export unlocks when both are done." : "Export unlocks after that.",
        ]
          .filter(Boolean)
          .join(" "),
      };
  }
}

interface Ctx {
  published: NextStep | null;
  publish: (n: NextStep | null) => void;
  guide: GuideControl | null;
}
const NextStepContext = createContext<Ctx>({ published: null, publish: () => undefined, guide: null });

export function NextStepProvider({ guide, children }: { guide: GuideControl; children: ReactNode }) {
  const [published, publish] = useState<NextStep | null>(null);
  const value = useMemo(() => ({ published, publish, guide }), [published, guide]);
  return <NextStepContext.Provider value={value}>{children}</NextStepContext.Provider>;
}

export const usePublishedNextStep = (): NextStep | null => useContext(NextStepContext).published;
/** The getting-started state (welcome band shown or not), for screens that render the welcome. */
export const useGuide = (): GuideControl | null => useContext(NextStepContext).guide;

/** Publish this screen's next step while it is mounted; `null` falls back to the step's default. */
export function useNextStep(n: NextStep | null): void {
  const { publish } = useContext(NextStepContext);
  const key = n ? JSON.stringify(n) : "";
  useEffect(() => {
    publish(n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, publish]);
  useEffect(() => () => publish(null), [publish]);
}
