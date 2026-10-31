import { useLayoutEffect, useRef } from "react";
import { useActiveJobs, useSources } from "../api/queries";
import { isPipelineJob, isReadingJob } from "../shell/jobStep";
import type { ExportStatus } from "../api/schema";
import { defaultNextStep, usePublishedNextStep } from "../shell/nextStep";
import Copy, { Keycap } from "./Copy";
import { keyLabel, stepForPath, GUIDE_STEPS } from "./guide";
import StepNav from "./StepNav";

const SHEET_VAR = "--guide-sheet";

/**
 * A pointer press in the rail never takes focus from the editor, the queue or a dialog (design 12 O2, section 4):
 * only a link (a step) moves focus, because following it is the point of the press.
 */
const keepFocus = (e: React.MouseEvent): void => {
  if (!(e.target as Element).closest("a")) e.preventDefault();
};

/**
 * The step rail (design 13 section 2.5.1): "Your next step" and the four steps. Docked on the left from the `wide`
 * breakpoint; below it a bottom sheet whose height is published as `--guide-sheet`, so pages pad for it and the
 * Verify action bar stays above it. Outside every `data-zone`, no `aria-modal`, no hotkeys, no focus() calls.
 */
export default function StepRail({ path, status, mock }: { path: string; status: ExportStatus | undefined; mock: boolean }) {
  const step = GUIDE_STEPS[stepForPath(path)];
  const published = usePublishedNextStep();
  const sources = useSources();
  const scanned = (sources.data ?? []).some((s) => s.kind === "scanned_pdf");
  // a job reading or scoring manuals is queued or running: Verify and Export wait for it (server truth, not a guess)
  const active = useActiveJobs();
  const pipeline = (active.data ?? []).filter(isPipelineJob);
  const scoring = pipeline.length > 0;
  const reading = scoring && pipeline.every(isReadingJob);
  const next = published ?? defaultNextStep(step.id, status, { scoring, reading });

  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const root = document.documentElement;
    if (!el) return;
    const measure = (): void => {
      const sheet = getComputedStyle(el).position === "fixed";
      root.style.setProperty(SHEET_VAR, sheet ? `${Math.ceil(el.getBoundingClientRect().height)}px` : "0px");
    };
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
      root.style.removeProperty(SHEET_VAR);
    };
  }, []);

  return (
    <aside
      ref={ref}
      aria-label="Getting started"
      data-testid="guide-panel"
      data-step={step.id}
      onMouseDown={keepFocus}
      className="fixed inset-x-0 bottom-0 z-30 flex flex-col gap-1.5 border-t border-line bg-rail px-3 pb-2 pt-2 short-narrow:py-1 shadow-[0_-6px_20px_-12px_rgb(39_32_26/0.25)] wide:static wide:z-auto wide:min-h-0 wide:flex-1 wide:gap-5 wide:overflow-y-auto wide:border-t-0 wide:bg-transparent wide:px-4 wide:pb-4 wide:pt-1 wide:shadow-none"
    >
      <section
        aria-labelledby="next-step-title"
        data-testid="next-step"
        className="min-w-0 wide:rounded-xl wide:border wide:border-act-line wide:bg-raised wide:p-3.5 wide:shadow-lift"
      >
        <h2 id="next-step-title" className="sr-only text-2xs font-bold uppercase tracking-[0.08em] text-act-ink wide:not-sr-only wide:mb-1">
          Your next step
        </h2>
        <p className="line-clamp-2 text-xs leading-snug text-ink wide:line-clamp-none wide:text-sm [@media(max-height:600px)]:max-wide:sr-only" data-testid="next-step-text">
          <Copy text={next.text} />
        </p>
        {next.keys?.length ? (
          <dl className="mt-3 hidden grid-cols-[auto_1fr] items-baseline gap-x-2.5 gap-y-1.5 text-xs text-ink wide:grid">
            {next.keys.map((k) => (
              <div key={k.id} className="contents">
                <dt>
                  <Keycap>{keyLabel(k.id)}</Keycap>
                </dt>
                <dd>{k.label}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </section>
      <StepNav path={path} status={status} live={{ scoring, reading }} />
      {mock || (scanned && step.id === "verify") ? (
        <div className="mt-auto hidden flex-col gap-1.5 wide:flex">
          {mock ? (
            <p role="note" className="rounded-lg border border-dashed border-line-strong px-3 py-2 text-2xs text-muted">
              <strong className="font-semibold text-ink">Demo models are on.</strong> Model output is placeholder text; real models are set in Scope, under Models.
            </p>
          ) : null}
          {scanned && step.id === "verify" ? (
            <p role="note" className="rounded-lg border border-dashed border-line-strong px-3 py-2 text-2xs text-muted">
              <strong className="font-semibold text-ink">Scanned pages</strong> are read with OCR, so more of their blocks come to you.
            </p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
