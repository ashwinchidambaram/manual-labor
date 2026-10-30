import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router-dom";
import ScopeScreen from "./scope/ScopeScreen";
import AppShell from "./shell/AppShell";
import AgentScreen from "./agent/AgentScreen";
import ExportScreen from "./export/ExportScreen";
import { NotFound } from "./shell/Stubs";
import VerifyScreen from "./verify/VerifyScreen";

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/scope" replace /> },
      { path: "/scope", element: <ScopeScreen /> },
      { path: "/verify", element: <VerifyScreen /> },
      { path: "/agent", element: <AgentScreen /> },
      { path: "/export", element: <ExportScreen /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initial: string) => createMemoryRouter(routes, { initialEntries: [initial] });
