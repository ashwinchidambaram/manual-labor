import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router-dom";
import ScopeScreen from "./scope/ScopeScreen";
import AppShell from "./shell/AppShell";
import { ComingSoon, NotFound } from "./shell/Stubs";

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/scope" replace /> },
      { path: "/scope", element: <ScopeScreen /> },
      { path: "/verify", element: <ComingSoon name="Verify" /> },
      { path: "/agent", element: <ComingSoon name="Agent" /> },
      { path: "/export", element: <ComingSoon name="Export" /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initial: string) => createMemoryRouter(routes, { initialEntries: [initial] });
