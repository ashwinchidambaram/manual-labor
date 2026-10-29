import createClient from "openapi-fetch";
import type { paths } from "./types";

/** Typed fetch client for the Manual Labor API. Vite proxies /api to 127.0.0.1:8765. */
export const client = createClient<paths>({
  baseUrl: typeof window !== "undefined" ? window.location.origin : "",
  // Resolve fetch at call time so test doubles (msw) installed later are honoured.
  fetch: (req) => globalThis.fetch(req),
});

/** Non-2xx API answer: the server body is `{detail, code}`. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail: string,
  ) {
    super(`${code}: ${detail}`);
    this.name = "ApiError";
  }
}

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Unwrap an openapi-fetch result, throwing ApiError for any non-2xx answer. */
export function unwrap<T>(r: Result<T>): T {
  if (r.error !== undefined || r.data === undefined) {
    const e = r.error as { detail?: unknown; code?: string } | undefined;
    const detail =
      typeof e?.detail === "string" ? e.detail : e?.detail ? JSON.stringify(e.detail) : r.response.statusText;
    throw new ApiError(r.response.status, e?.code ?? "http_error", detail || "request failed");
  }
  return r.data;
}
