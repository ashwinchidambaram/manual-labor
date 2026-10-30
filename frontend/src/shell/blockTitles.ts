import { useQuery } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { useSources } from "../api/queries";
import { cardTitle } from "../verify/labels";

export interface BlockTitle {
  title: string;
  page: number;
  doc: string;
}

/**
 * Human titles for blocks named elsewhere (Export blockers, Agent flags), from the review queue's own fields: the
 * section heading, else the document, else the page (design 13 section 2.8.3). Ids stay on screen beside them.
 * Read-only and best effort: if the queue cannot be read, callers fall back to the ids alone.
 */
export function useBlockTitles(enabled = true): Map<string, BlockTitle> {
  const sources = useSources();
  const q = useQuery({
    queryKey: ["verify", "titles"],
    queryFn: async () => unwrap(await client.GET("/api/verify/queue", { params: { query: { limit: 2000, view_threshold: 1 } } })),
    enabled,
    staleTime: 30_000,
    retry: false,
  });
  const names = new Map((sources.data ?? []).map((s) => [s.slug, s.filename]));
  const out = new Map<string, BlockTitle>();
  for (const it of q.data?.items ?? [])
    out.set(it.block_id, { title: cardTitle(it.section_title, names.get(it.doc_id), it.page, it.type), page: it.page, doc: names.get(it.doc_id) ?? it.doc_id });
  return out;
}
