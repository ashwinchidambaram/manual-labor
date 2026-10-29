import { useEffect, useRef } from "react";
import { HOTKEYS, displayKey, type HotkeyScope } from "../hotkeys";

const TITLES: Record<HotkeyScope, string> = {
  global: "Everywhere",
  scope: "Scope screen",
  tree: "Inside the group list",
  models: "Model panel",
};

/** Keyboard help, rendered from the same HOTKEYS map the handlers use. Focus-trapped dialog. */
export default function Help({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    return () => prior?.focus?.();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape" || e.key === "?") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === "Tab") {
      const f = ref.current?.querySelectorAll<HTMLElement>("button, [href], [tabindex='0']");
      if (!f?.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const scopes = (Object.keys(TITLES) as HotkeyScope[]).map((s) => ({
    scope: s,
    rows: Object.values(HOTKEYS).filter((h) => h.scope === s),
  }));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard help"
        className="max-h-[80vh] w-[32rem] overflow-auto rounded bg-white p-4 shadow-xl"
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Keyboard shortcuts</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-400 px-2 py-0.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          >
            Close
          </button>
        </div>
        {scopes.map(({ scope, rows }) => (
          <section key={scope} className="mb-3">
            <h3 className="text-sm font-semibold text-slate-700">{TITLES[scope]}</h3>
            <dl className="grid grid-cols-[9rem_1fr] gap-x-2 text-sm">
              {rows.map((h) => (
                <div key={h.label} className="contents">
                  <dt className="font-mono">{h.keys.map(displayKey).join(" / ")}</dt>
                  <dd>
                    {h.label}
                    {h.when ? <span className="text-slate-500"> ({h.when})</span> : null}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </div>
  );
}
