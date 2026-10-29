import { QueryClient } from "@tanstack/react-query";

export function makeQueryClient(opts: { retry?: number | false } = {}): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: opts.retry ?? 1, refetchOnWindowFocus: false } },
  });
}
