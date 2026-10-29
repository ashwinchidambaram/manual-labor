import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useProject } from "../api/queries";
import { useHotkeys } from "../hooks/useHotkeys";
import ErrorBoundary from "./ErrorBoundary";
import Help from "./Help";
import JobsBar from "./JobsBar";

const NAV = [
  { to: "/scope", label: "Scope", key: "1" },
  { to: "/verify", label: "Verify", key: "2" },
  { to: "/agent", label: "Agent", key: "3" },
  { to: "/export", label: "Export", key: "4" },
];

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

export default function AppShell() {
  const nav = useNavigate();
  const loc = useLocation();
  const project = useProject();
  const [help, setHelp] = useState(false);
  useHotkeys({
    help: () => setHelp((h) => !h),
    goScope: () => nav("/scope"),
    goVerify: () => nav("/verify"),
    goAgent: () => nav("/agent"),
    goExport: () => nav("/export"),
  });
  const unreachable = project.isError;
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {unreachable ? (
        <div role="alert" className="bg-red-700 px-4 py-1 text-sm text-white" data-testid="server-down">
          Server not reachable. Retrying every 3 seconds.
        </div>
      ) : null}
      <header className="flex flex-wrap items-center gap-4 border-b border-slate-300 bg-white px-4 py-2">
        <h1 className="text-lg font-semibold">Manual Labor</h1>
        <span className="text-sm text-slate-600" data-testid="project-name">
          {project.data?.name}
        </span>
        {project.data?.mock ? (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">mock models</span>
        ) : null}
        <nav aria-label="Screens" className="flex gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `rounded px-3 py-1 text-sm ${FOCUS} ${isActive ? "bg-slate-900 text-white" : "hover:bg-slate-200"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          onClick={() => setHelp(true)}
          aria-label="Keyboard help"
          className={`ml-auto rounded border border-slate-400 px-2 py-0.5 text-sm ${FOCUS}`}
        >
          ? Help
        </button>
        <div className="basis-full">
          <JobsBar />
        </div>
      </header>
      <ErrorBoundary key={loc.pathname}>
        <Outlet />
      </ErrorBoundary>
      {help ? <Help onClose={() => setHelp(false)} /> : null}
    </div>
  );
}
