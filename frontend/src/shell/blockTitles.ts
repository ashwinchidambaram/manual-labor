import { useQueries } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { useSources } from "../api/queries";
import type { BlockDetail } from "../api/schema";
import { cardTitle } from "../verify/labels";
import { blockKey, fetchBlock } from "../verify/useVerifyState";

export interface BlockTitle {
  title: string;
  page: number;
  doc: string;
}

export interface BlockTitles {
  titles: Map<string, BlockTitle>;
  /** every document's titles have arrived (or failed): group by them now, not before */
  ready: boolean;
}

/**
 * Human titles for blocks named elsewhere (Export blockers), from the review queue's own fields: the section heading,
 * else the document, else the page (design 13 section 2.8.3). Ids stay on screen beside them. One read per document
 * with `doc` set, so the result never depends on the reviewer's sort or document filter. Read-only and best effort:
 * a document whose queue cannot be read leaves its blocks untitled.
 */
export function useBlockTitles(enabled = true): BlockTitles {
  const sources = useSources();
  const slugs = (sources.data ?? []).map((s) => s.slug);
  const qs = useQueries({
    queries: slugs.map((slug) => ({
      queryKey: ["verify", "titles", slug],
      queryFn: async () =>
        unwrap(await client.GET("/api/verify/queue", { params: { query: { limit: 2000, view_threshold: 1, sort: "by_page", doc: slug } } })),
      enabled,
      staleTime: 30_000,
      retry: false,
    })),
  });
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename]));
  const titles = new Map<string, BlockTitle>();
  for (const q of qs)
    for (const it of q.data?.items ?? [])
      titles.set(it.block_id, { title: cardTitle(it.section_title, names.get(it.doc_id), it.page, it.type), page: it.page, doc: names.get(it.doc_id) ?? it.doc_id });
  const ready = !enabled || (sources.data !== undefined && qs.every((q) => q.isSuccess || q.isError));
  return { titles, ready };
}

/** "scanned.pdf, page 9, paragraph": a block outside the queue named by where it is (no section title is known). */
export function placeTitle(d: Pick<BlockDetail["block"], "doc_id" | "page" | "type">, docName: string | null | undefined): string {
  const where = cardTitle(null, null, d.page, d.type); // "Page 9, paragraph"
  return docName ? `${docName}, ${where[0].toLowerCase()}${where.slice(1)}` : where;
}

/**
 * Titles for flagged blocks (Agent): a flagged block is never in the review queue, so its title comes from its own
 * detail (`/api/verify/blocks/{id}`, cached under the same key Verify uses).
 */
export function useFlagTitles(ids: readonly string[]): Map<string, BlockTitle> {
  const sources = useSources();
  const qs = useQueries({
    queries: ids.map((id) => ({ queryKey: blockKey(id), queryFn: () => fetchBlock(id), staleTime: 30_000, retry: false })),
  });
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename]));
  const out = new Map<string, BlockTitle>();
  qs.forEach((q, i) => {
    const b = q.data?.block;
    if (!b || b.id !== ids[i]) return;
    out.set(ids[i], { title: placeTitle(b, names.get(b.doc_id)), page: b.page, doc: names.get(b.doc_id) ?? b.doc_id });
  });
  return out;
}
