import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { RouterProvider, type createBrowserRouter } from "react-router-dom";
import { makeQueryClient } from "./queryClient";
import { createRouter } from "./router";

export default function App({ router }: { router?: ReturnType<typeof createBrowserRouter> }) {
  const [qc] = useState(() => makeQueryClient());
  const [r] = useState(() => router ?? createRouter());
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={r} />
    </QueryClientProvider>
  );
}
