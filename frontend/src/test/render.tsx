import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { makeQueryClient } from "../queryClient";
import { createTestRouter } from "../router";

export function renderApp(path = "/scope") {
  const router = createTestRouter(path);
  const qc = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  const utils = render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, qc, user, ...utils };
}
