import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export interface ToastItem {
  id: number;
  kind: "error" | "info";
  message: string;
}
export interface ToastApi {
  error: (message: string) => void;
  info: (message: string) => void;
  dismiss: (id: number) => void;
}

const NOOP: ToastApi = { error: () => undefined, info: () => undefined, dismiss: () => undefined };
const Ctx = createContext<ToastApi>(NOOP);

/** Shared toasts for every screen. Errors persist until dismissed; info disappears after 6 s. */
export const useToast = (): ToastApi => useContext(Ctx);

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (kind: ToastItem["kind"], message: string) => {
      const id = ++seq;
      setItems((l) => [...l.filter((t) => t.message !== message), { id, kind, message }]);
      if (kind === "info") setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(
    () => ({ error: (m) => push("error", m), info: (m) => push("info", m), dismiss }),
    [push, dismiss],
  );
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="fixed bottom-[calc(var(--guide-sheet,0px)+1rem)] right-4 z-40 flex max-w-md flex-col gap-2" data-testid="toasts">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            data-testid="toast"
            className={`flex items-center gap-2 rounded-xl border px-3.5 py-2.5 text-sm shadow-lift ${
              t.kind === "error" ? "border-fail-line bg-fail-wash text-ink" : "border-line bg-raised text-ink"
            }`}
          >
            <span className="flex-1">{t.message}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              className="rounded border border-current px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
            >
              Dismiss
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
