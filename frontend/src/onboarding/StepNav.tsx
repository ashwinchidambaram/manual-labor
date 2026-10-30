import { NavLink } from "react-router-dom";
import type { ExportStatus } from "../api/schema";
import Hint from "./Hint";
import type { HintId } from "./hints";
import type { StepId } from "./guide";

export const STEPS: { id: StepId; to: string; label: string; hint: HintId; purpose: string }[] = [
  { id: "scope", to: "/scope", label: "Scope", hint: "navScope", purpose: "Choose what goes in" },
  { id: "verify", to: "/verify", label: "Verify", hint: "navVerify", purpose: "Check blocks against the page" },
  { id: "agent", to: "/agent", label: "Agent", hint: "navAgent", purpose: "Fix what you flag" },
  { id: "export", to: "/export", label: "Export", hint: "navExport", purpose: "Download the reviewed knowledge base" },
];

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

export interface StepState {
  /** short visible state, or null */
  short: string | null;
  /** the full sentence for screen readers */
  long: string;
  /** the step's server condition holds (only what the export gate can say: nothing left to review, export built) */
  done: boolean;
}

/** Step states from the export gate (the only source of these counts); nothing is shown that the API did not say. */
export function stepStates(path: string, st: ExportStatus | undefined): Record<StepId, StepState> {
  const out = {} as Record<StepId, StepState>;
  STEPS.forEach((s, i) => {
    const here = path.startsWith(s.to);
    let short: string | null = null;
    let long = "";
    let done = false;
    if (st) {
      const blockers = st.blockers ?? [];
      if (s.id === "verify" && (st.queued ?? 0) > 0) short = long = `${st.queued ?? 0} to review`;
      if (s.id === "verify" && (st.queued ?? 0) === 0 && blockers.length === 0) done = true;
      if (s.id === "agent" && st.open_flags > 0) short = long = plural(st.open_flags, "open flag");
      if (s.id === "export") {
        const why = [st.open_flags > 0 ? plural(st.open_flags, "open flag") : "", (st.queued ?? 0) > 0 ? `${st.queued ?? 0} to review` : ""].filter(Boolean);
        if (blockers.length > 0) {
          short = `locked: ${why[0] ?? plural(blockers.length, "blocker")}`;
          long = `locked: ${why.length ? why.join(", ") : plural(blockers.length, "blocking block")}`;
        } else {
          short = long = st.unlocked ? "ready" : "ready with an override";
        }
        done = !!st.summary;
      }
    }
    out[s.id] = {
      short: here ? "here" : short,
      long: `Step ${i + 1} of ${STEPS.length}.${here ? " You are here." : ""}${done ? " Done." : ""}${long ? ` ${long[0].toUpperCase()}${long.slice(1)}.` : ""}`,
      done: done && !here,
    };
  });
  return out;
}

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

/**
 * The four screens as numbered steps (design 12 O7, design 13 section 2.5.1). Docked on the left as a vertical journey
 * on wide screens, a row in the bottom sheet below that. Link names stay "Scope", "Verify"...; state goes in a
 * description, and every state is a word as well as a colour.
 */
export default function StepNav({ path, status }: { path: string; status: ExportStatus | undefined }) {
  const states = stepStates(path, status);
  return (
    <nav aria-label="Screens">
      <ol className="flex gap-1 wide:flex-col wide:gap-0">
        {STEPS.map((s, i) => {
          const st = states[s.id];
          const here = st.short === "here";
          const locked = s.id === "export" && !!status && (status.blockers ?? []).length > 0 && !here;
          const last = i === STEPS.length - 1;
          return (
            <li key={s.to} className="relative min-w-0 flex-1 wide:flex-none">
              {!last ? (
                <span
                  aria-hidden="true"
                  className={`absolute left-[1.3rem] top-[2.6rem] hidden h-[calc(100%-2.5rem)] w-0.5 rounded-full wide:block ${st.done ? "bg-ink" : "bg-line"}`}
                />
              ) : null}
              <Hint id={s.hint}>
                <NavLink
                  to={s.to}
                  aria-label={s.label}
                  aria-describedby={`step-state-${s.id}`}
                  data-testid={`step-${s.id}`}
                  className={({ isActive }) =>
                    `group/step flex min-h-[2.75rem] items-center gap-2 rounded-lg px-1.5 py-1.5 short-narrow:min-h-[2rem] short-narrow:py-0.5 transition-colors duration-150 ease-out-quart wide:items-start wide:gap-3 wide:px-2 wide:pb-3.5 wide:pt-2 ${FOCUS} ${
                      isActive ? "" : "hover:bg-sunk"
                    }`
                  }
                >
                  <span
                    aria-hidden="true"
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 short-narrow:h-6 short-narrow:w-6 text-xs font-bold tabular-nums ${
                      here ? "border-act bg-act text-act-on" : st.done ? "border-ink bg-ink text-raised" : "border-line bg-rail text-muted"
                    }`}
                  >
                    {st.done ? "✓" : i + 1}
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-sm font-semibold text-ink">{s.label}</span>
                      {st.short ? (
                        <span
                          aria-hidden="true"
                          data-testid={`step-short-${s.id}`}
                          className={`truncate text-2xs ${
                            here ? "font-bold uppercase tracking-[0.08em] text-act-ink" : `max-md:hidden ${locked ? "font-medium text-needs-ink" : "text-muted"}`
                          }`}
                        >
                          {st.short}
                        </span>
                      ) : null}
                    </span>
                    <span aria-hidden="true" className="hidden text-xs text-muted wide:block">
                      {s.purpose}
                    </span>
                  </span>
                </NavLink>
              </Hint>
              <span id={`step-state-${s.id}`} className="sr-only">
                {st.long}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
