import type { WhyItem } from "../api/schema";
import { signalHint } from "../onboarding/hints";
import { AttentionIcon } from "../shell/Icon";
import { FAITH_NOT_RUN, faithHeldSentence, human, label, plainDetail, STALE_NAME, weakestFromDetail } from "./labels";
import { pairForSignal, parserDiff, READER, readingLines, type LinePair, type ReadingPair } from "./parserDiff";

interface Props {
  why: WhyItem[];
  autoApproved: { confidence: number | null; threshold: number | null } | null;
  /** each parser's raw text, for the two readings */
  parserTexts?: Record<string, string>;
  /** the block's own faithfulness result (`block.faithfulness.passed`); null or undefined when cleanup has not run */
  faithfulnessPassed?: boolean | null;
  /** the parser whose text the block shows (`block.raw_source`): the text-layer side of `textlayer_vs_ocr` */
  rawSource?: string | null;
}

/** What one check found on this block. `noted`: under 1 on a block the checks cleared (a neutral row, not a card). */
export type WhyOutcome = "failed" | "held" | "noted" | "passed" | "not_run";

const READING_SIGNALS = new Set(["parser_agreement", "textlayer_vs_ocr", "ocr_min"]);

/**
 * The outcome of one signal. Faithfulness is decided by the block's check (`faithfulness.passed`), never by its value:
 * the scorer gives a passed check 0.5 or 0.9 when a model's cleanup was rejected or a reorder was needed, and only a
 * failed check 0.0 (manuallabor/scoring/pipeline.py).
 */
export function whyOutcome(w: WhyItem, faithfulnessPassed: boolean | null | undefined, cleared: boolean): WhyOutcome {
  if (w.value === null || w.value === undefined) return "not_run";
  if (w.name === "faithfulness") {
    if (faithfulnessPassed === false || (faithfulnessPassed == null && w.value === 0)) return "failed";
    if (w.detail === FAITH_NOT_RUN) return "not_run";
  }
  if (w.value < 1) return cleared ? "noted" : "held";
  return "passed";
}

/**
 * The verifier's evidence, read back from its detail: `verifier quoted "<span>"; raw "<raw>" -> clean "<clean>"`, each
 * part a JSON string literal (manuallabor/scoring/verifier.py `evidence_detail`). Null for any other detail, such as
 * one scored before the evidence rule.
 */
export function verifierEvidence(detail: string | null | undefined): { span: string; raw: string; clean: string } | null {
  if (!detail || !detail.startsWith("verifier quoted ")) return null;
  const lits = detail.match(/"(?:[^"\\]|\\.)*"/g);
  if (!lits || lits.length !== 3) return null;
  try {
    const [span, raw, clean] = lits.map((l) => JSON.parse(l) as unknown);
    if (typeof span !== "string" || typeof raw !== "string" || typeof clean !== "string") return null;
    return { span, raw, clean };
  } catch {
    return null;
  }
}

/** The change a verifier flag points at: cleanup's raw and clean text of it, then the span the verifier quoted. */
function VerifierEvidence({ ev }: { ev: { span: string; raw: string; clean: string } }) {
  const side = (t: string) => (t ? t : <em className="text-muted">nothing</em>);
  return (
    <dl data-testid="verifier-evidence" aria-label="The change the verifier points at" className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
      <dt className="pt-0.5 text-2xs font-medium text-muted">Raw</dt>
      <dd className="manual-text text-sm leading-relaxed text-ink">{side(ev.raw)}</dd>
      <dt className="pt-0.5 text-2xs font-medium text-muted">Clean</dt>
      <dd className="manual-text text-sm leading-relaxed text-ink">{side(ev.clean)}</dd>
      <dt className="pt-0.5 text-2xs font-medium text-muted">Verifier quoted</dt>
      <dd className="manual-text text-sm leading-relaxed text-muted">“{ev.span}”</dd>
    </dl>
  );
}

/** The lines where two readings differ, as two labelled lines in the manual's typeface (design 13 F4). */
function Readings({ pair, lines, testId }: { pair: ReadingPair; lines: LinePair[]; testId: string }) {
  if (!lines.length)
    return (
      <p className="mt-2 text-sm text-muted" data-testid="readings-agree">
        The two readings agree line for line; the difference is elsewhere.
      </p>
    );
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
    <div className="mt-2.5 space-y-3" data-testid={testId} aria-label="Where the two readings differ" role="group">
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

/**
 * The technical line under each check: the signal's short name, its value and what the scorer reported, verbatim.
 * A check that found nothing is named neutrally ("Looked for ..., found nothing"), and a critical one is only called
 * "a critical check": the "can hold a block on its own" clause belongs to a check that is holding one.
 */
function Tech({ w, outcome }: { w: WhyItem; outcome: WhyOutcome }) {
  const v = w.value === null || w.value === undefined ? "n/a" : `${w.value.toFixed(2)} of 1`;
  const quiet = outcome === "passed" || outcome === "not_run" || (w.name === "faithfulness" && outcome !== "failed");
  const name =
    w.name === "has_numeric_spec"
      ? "Rule: always reviewed (numeric spec)"
      : outcome === "passed" || (w.name === "faithfulness" && outcome === "held")
        ? `Looked for "${label(w.name)}", found nothing · ${v}`
        : `${label(w.name)} · ${v}`;
  return (
    <p className="mt-1.5 break-words text-2xs leading-relaxed text-muted">
      <span className="font-medium">
        {name}
        {w.critical ? (quiet ? " · a critical check" : " · critical: can hold a block on its own") : ""}
      </span>
      {w.detail ? (
        <>
          {" · "}
          <span className="font-mono">{plainDetail(w.name, w.detail)}</span>
        </>
      ) : null}
    </p>
  );
}

/**
 * Why this block needs a person (design 13 F1). Every signal is listed in the server's order. A signal that held the
 * block is a marigold card with its evidence; a signal that found nothing wrong is a quiet row with a tick and the
 * word "Passed"; a failed cleanup check is the only red. On a block the checks cleared, a signal under 1 is a neutral
 * row: it did not hold the block. The number and the scorer's own words follow as secondary text, never in place of
 * the sentence.
 */
export default function WhyList({ why, autoApproved, parserTexts = {}, faithfulnessPassed, rawSource }: Props) {
  const stale = why.filter((w) => w.kind === "stale");
  const signals = why.filter((w) => w.kind === "signal");
  const cleared = !!autoApproved;
  const outcomes = signals.map((w) => (w.name === "has_numeric_spec" ? "held" : whyOutcome(w, faithfulnessPassed, cleared)));
  const found = outcomes.filter((o) => o === "held" || o === "failed").length;
  const shownPairs = new Set<string>();
  let compareShown = false;
  return (
    <section aria-label="Why this needs you" className="text-sm">
      <h3 className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Why this needs you</h3>
      <p className="mt-1 text-sm text-muted">
        {cleared
          ? "The checks cleared this block. Each check is listed with what it found."
          : found === 0
            ? "No check found anything to look at. Each check is listed with what it found."
            : `${found === 1 ? "One check" : `${found} checks`} found something to look at. Each check is listed with what it found.`}
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
        {signals.map((w, i) => {
          const outcome = outcomes[i];
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
                  <Tech w={w} outcome={outcome} />
                </div>
              </li>
            );
          if (outcome === "passed" || outcome === "not_run" || outcome === "noted") {
            const sentence =
              outcome === "passed"
                ? human(w.name, false)
                : outcome === "noted"
                  ? w.name === "faithfulness"
                    ? faithHeldSentence(w.detail)
                    : human(w.name, true)
                  : w.name === "faithfulness"
                    ? "Cleanup has not run yet"
                    : label(w.name);
            const word = outcome === "passed" ? "Passed" : outcome === "noted" ? "Noted" : w.name === "faithfulness" ? "Not run yet" : "Not measured";
            return (
              <li key={w.name} data-testid="why-item" data-outcome={outcome} className="px-3.5 py-1.5">
                <p className="flex flex-wrap items-baseline gap-x-2.5 text-ink">
                  <span aria-hidden="true" className={`w-3 text-center font-bold ${outcome === "passed" ? "text-done-ink" : "text-muted"}`}>
                    {outcome === "passed" ? "✓" : outcome === "noted" ? "·" : "–"}
                  </span>
                  <span className={`text-xs font-semibold ${outcome === "passed" ? "text-done-ink" : "text-muted"}`}>{word}</span>
                  <span className={outcome === "passed" ? "" : "text-muted"}>{sentence}</span>
                </p>
                <div className="ml-[1.375rem]">
                  <Tech w={w} outcome={outcome} />
                </div>
              </li>
            );
          }
          const failed = outcome === "failed";
          const pair = READING_SIGNALS.has(w.name) ? pairForSignal(w.name, parserTexts, w.detail, rawSource) : null;
          const pairKey = pair ? `${pair.a}|${pair.b}` : null;
          const showReadings = pair !== null && pairKey !== null && !shownPairs.has(pairKey);
          const lines = showReadings && pair ? readingLines(pair.ta, pair.tb).slice(0, 3) : [];
          // the first comparison on screen keeps the long-standing test id; any later one is marked as more
          const firstReadings = lines.length > 0 && !compareShown;
          if (firstReadings) compareShown = true;
          if (pairKey) shownPairs.add(pairKey);
          const weak = w.name === "ocr_min" ? weakestFromDetail(w.detail) : null;
          const heading = failed ? human(w.name, true) : w.name === "faithfulness" ? faithHeldSentence(w.detail) : null;
          const evidence = w.name === "llm_verifier" ? verifierEvidence(w.detail) : null;
          return (
            <li
              key={w.name}
              data-testid="why-item"
              data-outcome={outcome}
              className={`rounded-xl border px-3.5 py-3 ${failed ? "border-fail-line bg-fail-wash" : "border-needs-line bg-raised"}`}
            >
              <p className="flex gap-2.5 font-semibold text-ink">
                <span aria-hidden="true" className={`grid w-3 shrink-0 place-items-center pt-[3px] font-bold ${failed ? "text-fail" : "text-needs-ink"}`}>
                  {failed ? "✕" : <AttentionIcon />}
                </span>
                <span>
                  {failed ? <span className="mr-1.5 text-xs font-bold text-fail">Failed</span> : null}
                  {heading ??
                    (weak ? (
                      <>
                        Least certain word: <span className="manual-text">“{weak}”</span>
                      </>
                    ) : (
                      human(w.name, true)
                    ))}
                </span>
              </p>
              <div className="ml-[1.375rem]">
                {weak ? <p className="mt-1 text-sm text-muted">Check every character of it against the page.</p> : null}
                {!weak && !heading && signalHint(w.name) && !showReadings ? <p className="mt-1 text-sm text-muted">{signalHint(w.name)}</p> : null}
                {showReadings && pair ? <Readings pair={pair} lines={lines} testId={firstReadings ? "parser-compare" : "parser-compare-more"} /> : null}
                {evidence ? <VerifierEvidence ev={evidence} /> : null}
                <Tech w={w} outcome={outcome} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
