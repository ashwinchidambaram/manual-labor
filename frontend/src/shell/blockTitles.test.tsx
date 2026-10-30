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
  it("useBlockTitles reads the queue sorted by page, so titles never depend on the reviewer's sort", async () => {
    installFake();
    const seen: string[] = [];
    server.use(
      http.get("*/api/verify/queue", ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ items: [makeQueueItem(1, { doc_id: "alpha", section_title: "2 Safety" })], total: 1, docs: [], counts: {}, cursor: {} });
      }),
    );
    const { result } = renderHook(() => useBlockTitles(true), { wrapper });
    await waitFor(() => expect(result.current.titles.size).toBe(1));
    expect(seen[0]).toContain("sort=by_page");
    expect(seen[0]).toContain("view_threshold=1");
    expect(seen[0]).toContain("doc=alpha"); // one read per document: the cursor's document filter never applies
    expect([...result.current.titles.values()][0]).toEqual({ title: "2 Safety", page: 1, doc: "alpha.pdf" });
    await waitFor(() => expect(result.current.ready).toBe(true));
  });
  it("useFlagTitles titles each flagged block from its own detail", async () => {
    installFake();
    server.use(http.get("*/api/verify/blocks/:id", ({ params }) => HttpResponse.json(makeBlockDetail(makeQueueItem(1, { block_id: String(params.id), doc_id: "beta", page: 2 })))));
    const { result } = renderHook(() => useFlagTitles(["b-beta-p002-01"]), { wrapper });
    await waitFor(() => expect(result.current.get("b-beta-p002-01")).toEqual({ title: "beta.pdf, page 2, paragraph", page: 2, doc: "beta.pdf" }));
  });
});
