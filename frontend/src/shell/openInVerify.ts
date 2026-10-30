import type { QueryClient } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";

// "Open block X in Verify" from another screen (design 09 section 11). The cursor PUT is a write the Verify screen did
// not make, so its own settled-writes counter (useVerifyWrites) cannot see it: this epoch counts these writes, and the
// Verify queue applies only a snapshot fetched after the latest one (useVerifyState), the same rule as for its own
// writes. Without it, a queue snapshot cached from an earlier visit (staleTime Infinity) was applied with its old
// cursor and Verify opened on the wrong block (F11).
let epoch = 0;

/** How many cursor writes were made from outside the Verify screen. */
export const verifyNavEpoch = (): number => epoch;

/**
 * Make `blockId` the Verify cursor's current block, keeping the reader's sort, view filter and document filter. With a
 * query client, the cached queue and the block's cached detail are dropped as well, so Verify opens on fresh data.
 */
export async function openInVerify(blockId: string, qc?: QueryClient): Promise<void> {
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
  epoch += 1;
  if (qc) {
    qc.removeQueries({ queryKey: ["verify", "queue"] });
    qc.removeQueries({ queryKey: ["verify", "block", blockId] });
  }
}
