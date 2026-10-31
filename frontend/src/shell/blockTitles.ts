import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { useSources } from "../api/queries";
import type { BlockDetail } from "../api/schema";
import { cardExcerpt, cardTitle } from "../verify/labels";
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
 * Titles for flagged blocks (Agent; design 09 section 14). A flagged block is never in the review queue, so its title
 * is built from the same sources as a queue card's, in this order: the section heading above it (`/api/verify/titles`,
 * the server's `section_titles`), else its excerpt (`cardExcerpt` over its own detail, the server's card rule), and the
 * file name only last ("x200-two-column.pdf, page 1, paragraph").
 */
export function useFlagTitles(ids: readonly string[]): Map<string, BlockTitle> {
  const sources = useSources();
  const qs = useQueries({
    queries: ids.map((id) => ({ queryKey: blockKey(id), queryFn: () => fetchBlock(id), staleTime: 30_000, retry: false })),
  });
  const sections = useQuery({
    queryKey: ["verify", "titles", ids.join(" ")],
    queryFn: async () => unwrap(await client.GET("/api/verify/titles", { params: { query: { ids: [...ids] } } })),
    enabled: ids.length > 0,
    staleTime: 30_000,
    retry: false,
  });
  const heading = new Map((sections.data ?? []).filter((r) => r.section_title && r.section_title.trim()).map((r) => [r.block_id, r.section_title!.trim()]));
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename]));
  const out = new Map<string, BlockTitle>();
  qs.forEach((q, i) => {
    const d = q.data;
    const b = d?.block;
    if (!d || !b || b.id !== ids[i]) return;
    const caption = b.figure_id ? ((d.figures ?? []).find((f) => f.figure_id === b.figure_id)?.record.caption_original ?? null) : null;
    const excerpt = b.type === "figure" && !caption ? "" : cardExcerpt(b, caption);
    const title = heading.get(b.id) ?? (excerpt || placeTitle(b, names.get(b.doc_id)));
    out.set(ids[i], { title, page: b.page, doc: names.get(b.doc_id) ?? b.doc_id });
  });
  return out;
}
