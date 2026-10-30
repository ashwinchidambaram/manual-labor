import { useEffect, useLayoutEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useActiveJobs, useExportStatus, useProject } from "../api/queries";
import { useHotkeys } from "../hooks/useHotkeys";
import Hint from "../onboarding/Hint";
import StepRail from "../onboarding/StepRail";
import { GUIDE_STEPS, stepForPath } from "../onboarding/guide";
import { useGuideState } from "../onboarding/useGuideState";
import ErrorBoundary from "./ErrorBoundary";
import Help from "./Help";
import JobsBar from "./JobsBar";
import { NextStepProvider } from "./nextStep";
import { ToastProvider } from "./Toast";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

/**
 * The frame (design 13 section 2.5.1). Wide screens: the step rail docked on the left, the screen beside it.
 * Narrower (and at 200% zoom): the brand row on top and the rail as a bottom sheet. On wide screens Verify gets a
 * fixed-height frame so its panes scroll on their own; everywhere else, and Verify when narrow, the page scrolls.
 */
export default function AppShell() {
  const nav = useNavigate();
  const loc = useLocation();
  const project = useProject();
  const exportStatus = useExportStatus();
  const guide = useGuideState(project.data?.root);
  const [help, setHelp] = useState(false);
  // the step indicator's counts follow the reader from screen to screen
  const refetchStatus = exportStatus.refetch;
  const [seenPath, setSeenPath] = useState(loc.pathname);
  useEffect(() => {
    if (loc.pathname === seenPath) return;
    setSeenPath(loc.pathname);
    void refetchStatus();
  }, [loc.pathname, seenPath, refetchStatus]);
  // a new screen opens at its top: on a flowing page (below `wide`, at 200% zoom) the window would otherwise keep the last
  // screen's scroll, and Verify opened from a scrolled Agent list would start below its page strip (design 13 section 9.3)
  useLayoutEffect(() => {
    if (window.scrollY > 0) window.scrollTo(0, 0);
  }, [loc.pathname]);
  // ...and the server's progress: each finished step of a running job can make a document ready (first-use report C10)
  const active = useActiveJobs();
  const jobsKey = (active.data ?? []).map((j) => `${j.id}:${j.status}:${j.units_done}`).join("|");
  const [seenJobs, setSeenJobs] = useState(jobsKey);
  useEffect(() => {
    if (jobsKey === seenJobs) return;
    setSeenJobs(jobsKey);
    void refetchStatus();
  }, [jobsKey, seenJobs, refetchStatus]);
  useHotkeys({
    help: () => setHelp((h) => !h),
    goScope: () => nav("/scope"),
    goVerify: () => nav("/verify"),
    goAgent: () => nav("/agent"),
    goExport: () => nav("/export"),
  });
  const unreachable = project.isError;
  const framed = loc.pathname.startsWith("/verify");
  return (
    <ToastProvider>
      <NextStepProvider guide={guide}>
        <div className="group/shell min-h-screen bg-paper text-ink wide:flex" data-guide={guide.open ? "open" : "closed"} data-frame={framed ? "fixed" : "flow"}>
          <div className="contents wide:sticky wide:top-0 wide:flex wide:h-screen wide:w-[15.5rem] wide:shrink-0 wide:flex-col wide:border-r wide:border-line wide:bg-rail">
            <header className="flex h-11 items-center gap-3 border-b border-line bg-rail px-4 wide:h-auto wide:items-start wide:border-b-0 wide:px-5 wide:pb-4 wide:pt-5">
              <div className="flex min-w-0 flex-1 items-baseline gap-2 wide:flex-col wide:gap-0">
                <h1 className="shrink-0 text-base font-bold tracking-[-0.01em] text-ink">Manual Labor</h1>
                <span className="truncate text-xs text-muted" data-testid="project-name">
                  {project.data?.name}
                </span>
              </div>
              {/* below `wide` the rail's footer note is not shown: model output is labelled in the header at every width */}
              {project.data?.mock ? (
                <p role="note" data-testid="demo-note" className="min-w-0 truncate rounded-md border border-dashed border-line-strong px-2 py-0.5 text-2xs text-muted wide:hidden">
                  <strong className="font-semibold text-ink">Demo models are on:</strong> model output is placeholder text
                </p>
              ) : null}
              <Hint id="help">
                <button
                  type="button"
                  onClick={() => setHelp(true)}
                  aria-label="Help"
                  data-help-button
                  className={`inline-flex min-h-[2rem] shrink-0 items-center gap-1.5 rounded-lg border border-line bg-raised px-2.5 text-xs font-medium text-ink hover:bg-sunk ${FOCUS}`}
                >
                  <span aria-hidden="true" className="font-bold">
                    ?
                  </span>
                  Help
                </button>
              </Hint>
            </header>
            <StepRail path={loc.pathname} status={exportStatus.data} mock={!!project.data?.mock} />
          </div>
          <div
            className={`flex min-w-0 flex-1 flex-col pb-[var(--guide-sheet,0px)] wide:pb-0 ${
              framed ? "wide:h-dvh wide:overflow-hidden" : ""
            }`}
          >
            {unreachable ? (
              <div role="alert" className="shrink-0 bg-fail px-4 py-1.5 text-sm text-act-on" data-testid="server-down">
                Server not reachable. Retrying every 3 seconds.
              </div>
            ) : null}
            <JobsBar />
            <ErrorBoundary key={loc.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
          {help ? (
            <Help
              onClose={() => setHelp(false)}
              step={GUIDE_STEPS[stepForPath(loc.pathname)].id}
              onShowGuide={() => {
                setHelp(false);
                guide.show();
                nav("/scope");
              }}
            />
          ) : null}
        </div>
      </NextStepProvider>
    </ToastProvider>
  );
}
