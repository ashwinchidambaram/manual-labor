import type { WhyItem } from "../api/schema";
import { signalHint } from "../onboarding/hints";
import { label, STALE_NAME } from "./labels";

interface Props {
  why: WhyItem[];
  autoApproved: { confidence: number | null; threshold: number | null } | null;
}

export default function WhyList({ why, autoApproved }: Props) {
  const stale = why.filter((w) => w.kind === "stale");
  const signals = why.filter((w) => w.kind === "signal");
  return (
    <section aria-label="Why this needs you" className="text-sm">
      <h3 className="font-semibold">Why this needs you</h3>
      <p className="text-xs text-slate-600">Each signal runs from 0 to 1; 1.00 means that check found nothing wrong.</p>
      {stale.map((w) => (
        <p key={w.name} data-testid="why-stale" className="mt-1 rounded bg-amber-100 px-2 py-0.5 text-amber-950">
          {w.name === STALE_NAME ? "The text changed since you approved this block" : w.name}
        </p>
      ))}
      {autoApproved ? (
        <p data-testid="why-auto" className="mt-1 text-slate-700">
          Auto-approved ({autoApproved.confidence?.toFixed(2) ?? "n/a"}{autoApproved.threshold !== null ? ` ≥ ${autoApproved.threshold.toFixed(2)}` : ""}); shown by your view filter
        </p>
      ) : null}
      <ul aria-label="Why this needs you, signals" className="mt-1 space-y-1">
        {signals.map((w) =>
          w.name === "has_numeric_spec" ? (
            <li key={w.name} data-testid="why-rule" className="rounded bg-violet-50 px-2 py-0.5">
              <strong>Rule: always reviewed</strong> (numeric spec). Blocks with numbers are always reviewed by a person: OCR mistakes in numbers are likely and a language model cannot see them.
              {w.detail ? <span className="block text-xs text-slate-700">{w.detail}</span> : null}
            </li>
          ) : (
            <li key={w.name} data-testid="why-item" className="px-2 py-0.5">
              <span className="font-medium">{label(w.name)}</span> <span className="tabular-nums">{w.value === null || w.value === undefined ? "n/a" : w.value.toFixed(2)}</span>
              {w.critical ? <span className="ml-1 rounded bg-red-100 px-1 text-xs text-red-900">critical</span> : null}
              {signalHint(w.name) ? <span className="block text-xs text-slate-600">{signalHint(w.name)}</span> : null}
              {w.detail ? <span className="block break-words text-xs text-slate-700">{w.detail}</span> : null}
            </li>
          ),
        )}
      </ul>
    </section>
  );
}
