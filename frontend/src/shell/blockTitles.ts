import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
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
 * Human titles for blocks named elsewhere (Export blockers), from the fields a queue card titles itself with: the
 * section heading, else the document, else the page (design 13 section 2.8.3). Ids stay on screen beside them. One
 * read of exactly these ids (`/api/verify/titles`), never a document's whole queue (review F12), and independent of
 * the reviewer's sort or document filter. Read-only and best effort: an id the server cannot place stays untitled.
 */
export function useBlockTitles(ids: readonly string[]): BlockTitles {
  const sources = useSources();
  const enabled = ids.length > 0;
  const q = useQuery({
    queryKey: ["verify", "titles", ids.join(" ")],
    queryFn: async () => unwrap(await client.GET("/api/verify/titles", { params: { query: { ids: [...ids] } } })),
    enabled,
    staleTime: 30_000,
    retry: false,
    // every override write changes the ids: the titles already read stay on screen while the new read is out
    placeholderData: keepPreviousData,
  });
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename]));
  const titles = new Map<string, BlockTitle>();
  for (const it of q.data ?? [])
    titles.set(it.block_id, { title: cardTitle(it.section_title, names.get(it.doc_id), it.page, it.type), page: it.page, doc: names.get(it.doc_id) ?? it.doc_id });
  // ready: this read settled, or the earlier one already titled every id listed now (the list does not flash)
  const settled = (q.isSuccess && !q.isPlaceholderData) || q.isError;
  const ready = !enabled || (sources.data !== undefined && (settled || ids.every((id) => titles.has(id))));
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
