import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useExportStatus, useProject } from "../api/queries";
import { useHotkeys } from "../hooks/useHotkeys";
import GuideDock from "../onboarding/GuideDock";
import Hint from "../onboarding/Hint";
import StepNav from "../onboarding/StepNav";
import { GUIDE_STEPS, stepForPath } from "../onboarding/guide";
import { useGuideState } from "../onboarding/useGuideState";
import ErrorBoundary from "./ErrorBoundary";
import Help from "./Help";
import JobsBar from "./JobsBar";
import { ToastProvider } from "./Toast";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

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
  useHotkeys({
    help: () => setHelp((h) => !h),
    goScope: () => nav("/scope"),
    goVerify: () => nav("/verify"),
    goAgent: () => nav("/agent"),
    goExport: () => nav("/export"),
  });
  const unreachable = project.isError;
  return (
    <ToastProvider>
      <div className="group/shell min-h-screen bg-slate-50 text-slate-900" data-guide={guide.open ? "open" : "closed"}>
        {unreachable ? (
          <div role="alert" className="bg-red-700 px-4 py-1 text-sm text-white" data-testid="server-down">
            Server not reachable. Retrying every 3 seconds.
          </div>
        ) : null}
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-300 bg-white px-4 py-2">
          <h1 className="text-lg font-semibold">Manual Labor</h1>
          <span className="text-sm text-slate-600" data-testid="project-name">
            {project.data?.name}
          </span>
          {project.data?.mock ? (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">mock models</span>
          ) : null}
          <StepNav path={loc.pathname} status={exportStatus.data} />
          <Hint id="help">
            <button
              type="button"
              onClick={() => setHelp(true)}
              aria-label="Help"
              data-help-button
              className={`ml-auto rounded border border-slate-400 px-2 py-0.5 text-sm ${FOCUS}`}
            >
              ? Help
            </button>
          </Hint>
          <div className="basis-full">
            <JobsBar />
          </div>
        </header>
        <div className={`pb-[var(--guide-sheet,0px)] ${guide.open ? "xl:flex xl:items-start xl:pb-0" : ""}`}>
          <div className="min-w-0 flex-1">
            <ErrorBoundary key={loc.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
          {guide.open ? <GuideDock path={loc.pathname} mock={!!project.data?.mock} onHide={guide.hide} saveError={guide.saveError} /> : null}
        </div>
        {help ? (
          <Help
            onClose={() => setHelp(false)}
            step={GUIDE_STEPS[stepForPath(loc.pathname)].id}
            onShowGuide={() => {
              setHelp(false);
              guide.show();
            }}
          />
        ) : null}
      </div>
    </ToastProvider>
  );
}
