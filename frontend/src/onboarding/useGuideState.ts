import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { client, unwrap } from "../api/client";
import type { GuideState } from "../api/schema";
import { GUIDE_VERSION } from "./guide";

export const guideKey = ["guide"] as const;
export const storageKey = (root: string | undefined): string => `manuallabor.guide.v${GUIDE_VERSION}.${root ?? "default"}`;

function readStorage(key: string): boolean | null {
  try {
    return window.localStorage.getItem(key) === "seen";
  } catch {
    return null; // storage unavailable: the caller falls back to session state
  }
}
function writeStorage(key: string, seen: boolean): boolean {
  try {
    if (seen) window.localStorage.setItem(key, "seen");
    else window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export interface GuideControl {
  /** the panel is docked */
  open: boolean;
  /** where the flag lives right now */
  source: "server" | "storage" | "session" | "loading";
  hide: () => void;
  show: () => void;
}

/**
 * Whether the getting-started panel is open (design 12 section 3). The server flag (per project, meta table) wins;
 * if the endpoint fails the flag lives in localStorage, and if storage throws, in memory for this page load.
 */
export function useGuideState(root: string | undefined): GuideControl {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: guideKey,
    queryFn: async () => unwrap(await client.GET("/api/ui/guide")),
    staleTime: Infinity,
    retry: false,
  });
  // session-only state: storage threw, or a PUT failed after the GET worked
  const [session, setSession] = useState<boolean | null>(null);
  const [, bump] = useState(0);
  const key = storageKey(root);

  const put = useCallback(
    async (seen: boolean) => {
      const prev = qc.getQueryData<GuideState>(guideKey);
      if (prev) qc.setQueryData<GuideState>(guideKey, { ...prev, seen, seen_at: seen ? prev.seen_at : null });
      try {
        const out = unwrap(await client.PUT("/api/ui/guide", { body: { seen } }));
        qc.setQueryData(guideKey, out);
      } catch {
        if (!writeStorage(key, seen)) setSession(!seen);
      }
    },
    [qc, key],
  );

  const set = useCallback(
    (seen: boolean) => {
      if (q.isError) {
        if (writeStorage(key, seen)) bump((n) => n + 1);
        else setSession(!seen);
        return;
      }
      void put(seen);
    },
    [q.isError, key, put],
  );

  if (session !== null) return { open: session, source: "session", hide: () => set(true), show: () => set(false) };
  if (q.isError) {
    if (root === undefined) return { open: false, source: "loading", hide: () => set(true), show: () => set(false) };
    const stored = readStorage(key);
    if (stored === null) return { open: true, source: "session", hide: () => set(true), show: () => set(false) };
    return { open: !stored, source: "storage", hide: () => set(true), show: () => set(false) };
  }
  if (!q.data) return { open: false, source: "loading", hide: () => set(true), show: () => set(false) };
  return { open: !q.data.seen, source: "server", hide: () => set(true), show: () => set(false) };
}
