import { NavLink } from "react-router-dom";
import type { ExportStatus } from "../api/schema";
import Hint from "./Hint";
import type { HintId } from "./hints";
import type { StepId } from "./guide";

export const STEPS: { id: StepId; to: string; label: string; hint: HintId }[] = [
  { id: "scope", to: "/scope", label: "Scope", hint: "navScope" },
  { id: "verify", to: "/verify", label: "Verify", hint: "navVerify" },
  { id: "agent", to: "/agent", label: "Agent", hint: "navAgent" },
  { id: "export", to: "/export", label: "Export", hint: "navExport" },
];

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

export interface StepState {
  /** short visible state, or null */
  short: string | null;
  /** the full sentence for screen readers */
  long: string;
}

/** Step states from the export gate (the only source of these counts); nothing is shown that the API did not say. */
export function stepStates(path: string, st: ExportStatus | undefined): Record<StepId, StepState> {
  const out = {} as Record<StepId, StepState>;
  STEPS.forEach((s, i) => {
    const here = path.startsWith(s.to);
    let short: string | null = null;
    let long = "";
    if (st) {
      const blockers = st.blockers ?? [];
      if (s.id === "verify" && (st.queued ?? 0) > 0) short = long = `${st.queued ?? 0} to review`;
      if (s.id === "agent" && st.open_flags > 0) short = long = plural(st.open_flags, "open flag");
      if (s.id === "export") {
        const why = [st.open_flags > 0 ? plural(st.open_flags, "open flag") : "", (st.queued ?? 0) > 0 ? `${st.queued ?? 0} to review` : ""].filter(Boolean);
        if (blockers.length > 0) {
          short = `locked: ${why[0] ?? plural(blockers.length, "blocker")}`;
          long = `locked: ${why.length ? why.join(", ") : plural(blockers.length, "blocking block")}`;
        } else {
          short = long = st.unlocked ? "ready" : "ready with an override";
        }
      }
    }
    out[s.id] = {
      short: here ? "here" : short,
      long: `Step ${i + 1} of ${STEPS.length}.${here ? " You are here." : ""}${long ? ` ${long[0].toUpperCase()}${long.slice(1)}.` : ""}`,
    };
  });
  return out;
}

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

/** The four screens as numbered steps (design 12 O7). Link names stay "Scope", "Verify"...; state goes in a description. */
export default function StepNav({ path, status }: { path: string; status: ExportStatus | undefined }) {
  const states = stepStates(path, status);
  return (
    <nav aria-label="Screens" className="flex flex-wrap gap-1">
      {STEPS.map((s, i) => {
        const st = states[s.id];
        const locked = s.id === "export" && !!status && (status.blockers ?? []).length > 0 && st.short !== "here";
        return (
          <span key={s.to} className="contents">
            <Hint id={s.hint}>
              <NavLink
                to={s.to}
                aria-label={s.label}
                aria-describedby={`step-state-${s.id}`}
                data-testid={`step-${s.id}`}
                className={({ isActive }) =>
                  `group/step flex items-center gap-1.5 rounded px-2.5 py-1 text-sm ${FOCUS} ${isActive ? "bg-slate-900 text-white" : "text-slate-900 hover:bg-slate-200"}`
                }
              >
                <span aria-hidden="true" className="tabular-nums text-xs opacity-70">
                  {i + 1}
                </span>
                <span>{s.label}</span>
                {st.short ? (
                  <span
                    aria-hidden="true"
                    data-testid={`step-short-${s.id}`}
                    className={`rounded px-1 text-xs ${
                      st.short === "here" ? "opacity-80" : locked ? "bg-amber-100 text-amber-950" : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {st.short}
                  </span>
                ) : null}
              </NavLink>
            </Hint>
            <span id={`step-state-${s.id}`} className="sr-only">
              {st.long}
            </span>
          </span>
        );
      })}
    </nav>
  );
}
