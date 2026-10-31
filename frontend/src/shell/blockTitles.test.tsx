import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { makeQueryClient } from "../queryClient";
import { installFake, server } from "../test/server";
import { makeBlockDetail, makeQueueItem } from "../test/verifyFake";
import { placeTitle, useBlockTitles, useFlagTitles } from "./blockTitles";

const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={makeQueryClient({ retry: false })}>{children}</QueryClientProvider>;

describe("blockTitles", () => {
  it("placeTitle names a block by file, page and type", () => {
    expect(placeTitle({ doc_id: "scanned", page: 9, type: "paragraph" }, "scanned.pdf")).toBe("scanned.pdf, page 9, paragraph");
    expect(placeTitle({ doc_id: "scanned", page: 9, type: "caption" }, null)).toBe("Page 9, caption");
  });
  it("useBlockTitles reads only the ids it is given, in one request, never a document's whole queue", async () => {
    installFake();
    const seen: string[] = [];
    server.use(
      http.get("*/api/verify/queue", ({ request }) => {
        seen.push(`queue ${new URL(request.url).search}`);
        return HttpResponse.json({ items: [], total: 0, docs: [], counts: {}, cursor: {} });
      }),
      http.get("*/api/verify/titles", ({ request }) => {
        seen.push(`titles ${new URL(request.url).searchParams.getAll("ids").join(",")}`);
        return HttpResponse.json([{ block_id: "b-alpha-p001-01", doc_id: "alpha", page: 1, type: "paragraph", section_title: "2 Safety" }]);
      }),
    );
    const { result } = renderHook(() => useBlockTitles(["b-alpha-p001-01", "b-alpha-p004-02"]), { wrapper });
    await waitFor(() => expect(result.current.titles.size).toBe(1));
    expect(seen).toEqual(["titles b-alpha-p001-01,b-alpha-p004-02"]);
    expect(result.current.titles.get("b-alpha-p001-01")).toEqual({ title: "2 Safety", page: 1, doc: "alpha.pdf" });
    await waitFor(() => expect(result.current.ready).toBe(true));
  });
  it("useBlockTitles with no ids asks nothing and is ready", async () => {
    installFake();
    const seen: string[] = [];
    server.use(http.get("*/api/verify/titles", () => (seen.push("titles"), HttpResponse.json([]))));
    const { result } = renderHook(() => useBlockTitles([]), { wrapper });
    expect(result.current.ready).toBe(true);
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toEqual([]);
  });
  it("useFlagTitles titles a flagged block by its section heading, else its excerpt, the file name last", async () => {
    installFake();
    server.use(
      http.get("*/api/verify/blocks/:id", ({ params }) => HttpResponse.json(makeBlockDetail(makeQueueItem(1, { block_id: String(params.id), doc_id: "beta", page: 2 })))),
      http.get("*/api/verify/titles", () => HttpResponse.json([{ block_id: "b-beta-p002-01", doc_id: "beta", page: 2, type: "paragraph", section_title: "1.1 Overview" }])),
    );
    const { result } = renderHook(() => useFlagTitles(["b-beta-p002-01", "b-beta-p002-02"]), { wrapper });
    await waitFor(() => expect(result.current.get("b-beta-p002-01")).toEqual({ title: "1.1 Overview", page: 2, doc: "beta.pdf" }));
    await waitFor(() => expect(result.current.get("b-beta-p002-02")).toEqual({ title: "Text of b-beta-p002-02 set to 0.25 mm.", page: 2, doc: "beta.pdf" }));
  });
  it("useFlagTitles falls back to the place (file, page, type) only when the block has no text to show", async () => {
    installFake();
    server.use(
      http.get("*/api/verify/blocks/:id", ({ params }) =>
        HttpResponse.json(makeBlockDetail(makeQueueItem(1, { block_id: String(params.id), doc_id: "beta", page: 2, type: "figure" }), {}, { figure_id: null })),
      ),
    );
    const { result } = renderHook(() => useFlagTitles(["b-beta-p002-03"]), { wrapper });
    await waitFor(() => expect(result.current.get("b-beta-p002-03")).toEqual({ title: "beta.pdf, page 2, figure", page: 2, doc: "beta.pdf" }));
  });
});
