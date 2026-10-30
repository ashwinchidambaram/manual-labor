import { useEffect, useRef, useState } from "react";
import { HOTKEYS, LOCAL_KEYS, SCOPE_TITLES, type HotkeyScope } from "../hotkeys";
import Copy, { Keycap } from "../onboarding/Copy";
import { GLOSSARY } from "../onboarding/glossary";
import { GUARANTEES, GUIDE_STEPS, keyLabel, keycap, type StepId } from "../onboarding/guide";

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";
const TABS = [
  { id: "guide", label: "Guide" },
  { id: "keys", label: "Keyboard shortcuts" },
  { id: "glossary", label: "Glossary" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function Keys({ keys, mod = false }: { keys: readonly string[]; mod?: boolean }) {
  return (
    <>
      {keys.map((k, i) => (
        <span key={k}>
          {i > 0 ? <span className="text-muted"> / </span> : null}
          <Keycap>{`${mod ? "Ctrl/Cmd+" : ""}${keycap(k)}`}</Keycap>
        </span>
      ))}
    </>
  );
}

/**
 * Help: the getting-started guide, the keyboard shortcuts (rendered from the same HOTKEYS map the handlers use) and
 * the glossary. Focus-trapped dialog; Esc or ? closes it and focus returns to where it was.
 */
export default function Help({ onClose, step = "scope", onShowGuide }: { onClose: () => void; step?: StepId; onShowGuide?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>("guide");
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    // opened from a screen, the guide starts at that screen's step (scrolling only; focus stays on Close)
    ref.current?.querySelector<HTMLElement>(`[data-guide-step='${step}']`)?.scrollIntoView?.({ block: "start" });
    return () => prior?.focus?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape" || e.key === "?") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === "Tab") {
      const f = Array.from(ref.current?.querySelectorAll<HTMLElement>("button, [href], [tabindex='0']") ?? []).filter(
        (el) => el.tabIndex >= 0 && !el.closest("[hidden]"),
      );
      if (!f.length) return;
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
  const onTabKey = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const i = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(i + dir + TABS.length) % TABS.length].id;
    setTab(next);
    const list = e.currentTarget;
    requestAnimationFrame(() => list.querySelector<HTMLElement>(`[data-tab='${next}']`)?.focus());
  };

  const scopes = (Object.keys(SCOPE_TITLES) as HotkeyScope[])
    .map((s) => ({ scope: s, rows: Object.values(HOTKEYS).filter((h) => h.scope === s) }))
    .filter((g) => g.rows.length > 0);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(39_32_26/0.38)] p-4" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Help"
        className="flex max-h-[85vh] w-[44rem] max-w-full flex-col overflow-hidden rounded-2xl bg-raised text-ink shadow-[0_24px_60px_-20px_rgb(39_32_26/0.45)]"
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 px-6 pt-5">
          <h2 className="text-xl font-semibold">Help</h2>
          <button type="button" onClick={onClose} className={`min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-3 text-sm font-medium hover:bg-sunk ${FOCUS}`}>
            Close
          </button>
        </div>
        <div role="tablist" aria-label="Help sections" className="mt-3 flex gap-1 border-b border-line px-6" onKeyDown={onTabKey}>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`help-tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`help-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              data-tab={t.id}
              onClick={() => setTab(t.id)}
              className={`-mb-px min-h-[2.5rem] border-b-2 px-3 text-sm ${FOCUS} ${
                tab === t.id ? "border-act font-semibold text-ink" : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          <section role="tabpanel" id="help-panel-guide" aria-labelledby="help-tab-guide" hidden={tab !== "guide"} tabIndex={0} data-testid="help-guide" className={`min-h-0 flex-1 overflow-auto px-6 py-4 ${FOCUS} focus-visible:ring-inset`}>
            {onShowGuide ? (
              <p className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-sunk px-3.5 py-2.5 text-sm text-muted">
                The four steps are always on screen: on the left, or along the bottom in a narrow window. The welcome on Scope can be shown again.
                <button type="button" onClick={onShowGuide} data-testid="show-guide" className={`min-h-[2rem] rounded-lg border border-line-strong bg-raised px-2.5 text-sm font-medium text-ink hover:bg-sunk ${FOCUS}`}>
                  Show the welcome again
                </button>
              </p>
            ) : null}
            <ol className="space-y-4">
              {GUIDE_STEPS.map((s, i) => (
                <li key={s.id} data-guide-step={s.id} className="scroll-mt-2">
                  <h3 className="flex items-baseline gap-2 text-base font-semibold text-ink">
                    <span aria-hidden="true" className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-sunk text-xs font-bold text-muted ring-1 ring-inset ring-line">
                      {i + 1}
                    </span>
                    <span>
                      <span className="sr-only">{i + 1}. </span>
                      {s.title}
                    </span>
                  </h3>
                  <p className="ml-8 mt-1 max-w-[65ch] text-sm text-muted">{s.what}</p>
                  <ul className="ml-8 mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink marker:text-line-strong">
                    {s.do.map((d) => (
                      <li key={d}>
                        <Copy text={d} />
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
            <h3 className="mt-6 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">How it works</h3>
            <dl className="mt-2 space-y-3 text-sm">
              {GUARANTEES.map((g) => (
                <div key={g.claim}>
                  <dt className="font-semibold text-ink">{g.claim}</dt>
                  <dd className="max-w-[65ch] text-muted">{g.how}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section role="tabpanel" id="help-panel-keys" aria-labelledby="help-tab-keys" hidden={tab !== "keys"} tabIndex={0} data-testid="help-keys" className={`min-h-0 flex-1 overflow-auto px-6 py-4 ${FOCUS} focus-visible:ring-inset`}>
            {scopes.map(({ scope, rows }) => (
              <section key={scope} className="mb-4">
                <h3 className="mb-1 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">{SCOPE_TITLES[scope]}</h3>
                <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
                  {rows.map((h) => (
                    <div key={h.label} className="contents" data-testid="hotkey-row">
                      <dt>
                        <Keys keys={h.keys} mod={!!h.mod} />
                      </dt>
                      <dd>
                        {h.label}
                        {h.when ? <span className="text-muted"> ({h.when})</span> : null}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
            <section className="mb-1">
              <h3 className="mb-1 text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Inside a widget</h3>
              <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
                {LOCAL_KEYS.map((k) => (
                  <div key={k.widget} className="contents">
                    <dt>
                      <Keys keys={k.keys} />
                    </dt>
                    <dd>
                      {k.widget}: {k.label}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          </section>
          <section role="tabpanel" id="help-panel-glossary" aria-labelledby="help-tab-glossary" hidden={tab !== "glossary"} tabIndex={0} data-testid="help-glossary" className={`min-h-0 flex-1 overflow-auto px-6 py-4 ${FOCUS} focus-visible:ring-inset`}>
            <dl className="space-y-2 text-sm">
              {GLOSSARY.map((g) => (
                <div key={g.id} data-testid="glossary-entry">
                  <dt className="font-semibold text-ink">
                    {g.term}
                    {g.hotkey ? (
                      <span className="ml-2 font-normal">
                        <Keycap>{keyLabel(g.hotkey)}</Keycap>
                      </span>
                    ) : null}
                  </dt>
                  <dd className="max-w-[65ch] text-muted">{g.text}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}
