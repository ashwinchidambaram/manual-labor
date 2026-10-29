// Ordering guard between local selection edits and selection fetches (review fix: stale fetch overwrote
// newer state). `version` grows on every local mutation and every PUT acknowledgement; `pending` counts
// operations the server has not confirmed. A fetch that started or ended while either moved is stale.
export const selSync = { version: 0, pending: 0 };

export function bumpSelectionVersion(): void {
  selSync.version += 1;
}
