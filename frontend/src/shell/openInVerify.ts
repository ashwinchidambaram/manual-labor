import { client, unwrap } from "../api/client";

/** Make `blockId` the Verify cursor's current block, keeping the reader's sort, view filter and document filter. */
export async function openInVerify(blockId: string): Promise<void> {
  const cur = unwrap(await client.GET("/api/verify/cursor"));
  unwrap(
    await client.PUT("/api/verify/cursor", {
      body: {
        sort: cur.sort,
        view_threshold: cur.view_threshold ?? null,
        doc_filter: cur.doc_filter ?? null,
        current_block_id: blockId,
        request_id: crypto.randomUUID(),
      },
    }),
  );
}
