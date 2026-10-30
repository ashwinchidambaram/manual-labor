import type { WhyItem } from "../api/schema";
import { signalHint } from "../onboarding/hints";
import { AttentionIcon } from "../shell/Icon";
import { human, label, STALE_NAME, weakestFromDetail } from "./labels";
import { parserDiff, pickPair, READER, readingLines } from "./parserDiff";

interface Props {
  why: WhyItem[];
  autoApproved: { confidence: number | null; threshold: number | null } | null;
  /** each parser's raw text, for the two readings */
  parserTexts?: Record<string, string>;
}

const READING_SIGNALS = new Set(["parser_agreement", "textlayer_vs_ocr"]);

/** The lines where two readings differ, as two labelled lines in the manual's typeface (design 13 F4). */
function Readings({ texts }: { texts: Record<string, string> }) {
  const pair = pickPair(texts);
  if (!pair) return null;
  const lines = readingLines(pair.ta, pair.tb).slice(0, 3);
  if (!lines.length) return null;
  const marked = (spans: { text: string; differs: boolean }[]) =>
    spans.map((s, i) =>
      s.differs ? (
        <mark key={i} data-testid="parser-diff" className="rounded-[3px] bg-needs-wash text-inherit shadow-[0_0_0_2px_var(--needs-wash)]">
          {s.text}
        </mark>
      ) : (
        <span key={i}>{s.text}</span>
      ),
    );
  return (
    <div className="mt-2.5 space-y-3" data-testid="parser-compare" aria-label="Where the two readings differ" role="group">
      {lines.map((l) => {
        const d = parserDiff(l.a, l.b);
        return (
          <dl key={l.line} className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="col-span-2 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Line {l.line}</dt>
            <dt className="pt-0.5 text-2xs font-medium text-muted">{READER[pair.a] ?? pair.a}</dt>
            <dd className="manual-text text-sm leading-relaxed text-ink">{l.a ? marked(d.a) : <em className="text-muted">nothing read</em>}</dd>
            <dt className="pt-0.5 text-2xs font-medium text-muted">{READER[pair.b] ?? pair.b}</dt>
            <dd className="manual-text text-sm leading-relaxed text-ink">{l.b ? marked(d.b) : <em className="text-muted">nothing read</em>}</dd>
          </dl>
        );
      })}
    </div>
  );
}

/** The technical line under each check: the signal's short name, its value and what the scorer reported, verbatim. */
function Tech({ w }: { w: WhyItem }) {
  const v = w.value === null || w.value === undefined ? "n/a" : `${w.value.toFixed(2)} of 1`;
  return (
    <p className="mt-1.5 break-words text-2xs leading-relaxed text-muted">
      <span className="font-medium">
        {w.name === "has_numeric_spec" ? "Rule: always reviewed (numeric spec)" : `${label(w.name)} · ${v}`}
        {w.critical ? " · critical: can hold a block on its own" : ""}
      </span>
      {w.detail ? (
        <>
          {" · "}
          <span className="font-mono">{w.detail}</span>
        </>
      ) : null}
    </p>
  );
}

/**
 * Why this block needs a person (design 13 F1). Every signal is listed in the server's order. A signal that held the
 * block is a marigold card with its evidence; a signal that found nothing wrong is a quiet row with a tick and the
 * word "Passed"; a failed cleanup check is the only red. The number and the scorer's own words follow as secondary
 * text, never in place of the sentence.
 */
export default function WhyList({ why, autoApproved, parserTexts = {} }: Props) {
  const stale = why.filter((w) => w.kind === "stale");
  const signals = why.filter((w) => w.kind === "signal");
  const heldCount = signals.filter((w) => w.name === "has_numeric_spec" || (w.value ?? 1) < 1).length + stale.length;
  let readingsShown = false;
  return (
    <section aria-label="Why this needs you" className="text-sm">
      <h3 className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Why this needs you</h3>
      <p className="mt-1 text-sm text-muted">
        {autoApproved
          ? "The checks cleared this block. Each check is listed with what it found."
          : `${heldCount === 1 ? "One thing" : `${heldCount} things`} held this block for a person. Each check is listed with what it found.`}
      </p>
      {stale.map((w) => (
        <p key={w.name} data-testid="why-stale" className="mt-2 flex gap-2 rounded-xl bg-needs-wash px-3 py-2 text-ink">
          <AttentionIcon className="mt-[3px] shrink-0 text-needs-ink" />
          {w.name === STALE_NAME ? "The text changed since you approved this block" : w.name}
        </p>
      ))}
      {autoApproved ? (
        <p data-testid="why-auto" className="mt-2 flex gap-2 rounded-xl bg-done-wash px-3 py-2 text-ink">
          <span aria-hidden="true" className="font-bold text-done-ink">
            ✓
          </span>
          <span>
            Auto-approved ({autoApproved.confidence?.toFixed(2) ?? "n/a"}
            {autoApproved.threshold !== null ? ` ≥ ${autoApproved.threshold.toFixed(2)}` : ""}); shown by your view filter
          </span>
        </p>
      ) : null}
      <ul aria-label="Why this needs you, signals" className="mt-3 flex flex-col gap-2">
        {signals.map((w) => {
          if (w.name === "has_numeric_spec")
            return (
              <li key={w.name} data-testid="why-rule" className="rounded-xl border border-line bg-raised px-3.5 py-3">
                <p className="flex gap-2.5 font-semibold text-ink">
                  <span aria-hidden="true" className="w-3 text-center font-bold text-ink">
                    #
                  </span>
                  {human(w.name, true)}
                </p>
                <p className="ml-[1.375rem] mt-1 text-sm text-muted">
                  Blocks with numbers are always reviewed by a person: OCR mistakes in numbers are likely and a language model cannot see them. Approving
                  records them as checked by you.
                </p>
                <div className="ml-[1.375rem]">
                  <Tech w={w} />
                </div>
              </li>
            );
          const measured = w.value !== null && w.value !== undefined;
          const held = measured && (w.value as number) < 1;
          const failed = held && w.name === "faithfulness";
          if (!held)
            return (
              <li key={w.name} data-testid="why-item" data-outcome={measured ? "passed" : "not_run"} className="px-3.5 py-1.5">
                <p className="flex flex-wrap items-baseline gap-x-2.5 text-ink">
                  <span aria-hidden="true" className={`w-3 text-center font-bold ${measured ? "text-done-ink" : "text-muted"}`}>
                    {measured ? "✓" : "–"}
                  </span>
                  <span className={`text-xs font-semibold ${measured ? "text-done-ink" : "text-muted"}`}>{measured ? "Passed" : "Not measured"}</span>
                  <span>{human(w.name, false)}</span>
                </p>
                <div className="ml-[1.375rem]">
                  <Tech w={w} />
                </div>
              </li>
            );
          const showReadings = READING_SIGNALS.has(w.name) && !readingsShown;
          if (showReadings) readingsShown = true;
          const weak = w.name === "ocr_min" ? weakestFromDetail(w.detail) : null;
          return (
            <li
              key={w.name}
              data-testid="why-item"
              data-outcome={failed ? "failed" : "held"}
              className={`rounded-xl border px-3.5 py-3 ${failed ? "border-fail-line bg-fail-wash" : "border-needs-line bg-raised"}`}
            >
              <p className="flex gap-2.5 font-semibold text-ink">
                <span aria-hidden="true" className={`grid w-3 shrink-0 place-items-center pt-[3px] font-bold ${failed ? "text-fail" : "text-needs-ink"}`}>
                  {failed ? "✕" : <AttentionIcon />}
                </span>
                <span>
                  {failed ? <span className="mr-1.5 text-xs font-bold text-fail">Failed</span> : null}
                  {weak ? (
                    <>
                      Least certain word: <span className="manual-text">“{weak}”</span>
                    </>
                  ) : (
                    human(w.name, true)
                  )}
                </span>
              </p>
              <div className="ml-[1.375rem]">
                {weak ? <p className="mt-1 text-sm text-muted">Check every character of it against the page.</p> : null}
                {!weak && signalHint(w.name) && !showReadings ? <p className="mt-1 text-sm text-muted">{signalHint(w.name)}</p> : null}
                {showReadings ? <Readings texts={parserTexts} /> : null}
                <Tech w={w} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
