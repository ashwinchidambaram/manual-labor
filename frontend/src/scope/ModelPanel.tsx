import { useState } from "react";
import { useApplyTier, useRunProbe } from "../api/queries";
import type { ScopeModels, ModelRef, Tier } from "../api/schema";
import Hint from "../onboarding/Hint";

const TASKS = ["cleanup", "grouping", "vision", "verifier", "embeddings"] as const;
const OPTIONAL = ["metadata", "agent"] as const;
const TIERS: Tier[] = ["small", "medium", "large", "api"];
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

const fmt = (m: ModelRef | null | undefined): string => (m ? `${m.provider}/${m.model}` : "not set");

export default function ModelPanel({ data }: { data: ScopeModels }) {
  const apply = useApplyTier();
  const probe = useRunProbe();
  const sug = data.suggestions ?? null;
  const [picked, setPicked] = useState<Tier | null>(null);
  const tier: Tier = picked ?? sug?.default_tier ?? "medium";
  const p = data.probe ?? null;
  const rows = [...TASKS, ...OPTIONAL.filter((t) => data.models[t])];

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const group = e.currentTarget;
    const next = TIERS[(TIERS.indexOf(tier) + dir + TIERS.length) % TIERS.length];
    setPicked(next);
    requestAnimationFrame(() => group.querySelector<HTMLElement>(`[data-tier="${next}"]`)?.focus());
  };
  const cmds = sug?.pull_commands?.[tier] ?? [];
  return (
    <section aria-label="Models" data-zone="models" data-testid="model-panel" className="flex flex-col gap-3 text-ink">
      <div>
        <h2 className="text-base font-semibold">Models and hardware</h2>
        <p className="text-xs text-muted">
          {rows.every((t) => data.models[t]?.provider === "mock")
            ? "Demo placeholders: model output is placeholder text until you apply a tier."
            : "The model each task uses."}
        </p>
      </div>
      <table className="w-full text-left text-xs" data-testid="model-table">
        <thead>
          <tr>
            <th scope="col" className="pb-1 pr-2 font-medium text-muted">Task</th>
            <th scope="col" className="pb-1 font-medium text-muted">Model</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t} data-testid={`model-${t}`}>
              <th scope="row" className="pr-2 font-normal">{t}</th>
              <td className="break-all font-mono text-2xs">{fmt(data.models[t])}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {p ? (
        <p className="text-xs text-muted" data-testid="hardware">
          Hardware: {p.ram_gb} GB RAM
          {p.gpu ? `, GPU ${p.gpu.name ?? p.gpu.vendor}${p.gpu.vram_gb ? ` (${p.gpu.vram_gb} GB)` : ""}` : ", no GPU"}; about{" "}
          {p.effective_model_memory_gb} GB usable for models. Ollama:{" "}
          {p.ollama.reachable ? `reachable (${p.ollama.models.length} models)` : p.ollama.installed ? "installed, not running" : "not installed"}.
        </p>
      ) : (
        <div>
          <p className="mb-1 text-xs text-muted">No hardware probe yet.</p>
          <button
            type="button"
            onClick={() => probe.mutate()}
            disabled={probe.isPending}
            className={`min-h-[2.25rem] rounded-lg border border-line bg-raised px-3 text-sm font-medium hover:bg-sunk ${FOCUS}`}
          >
            Run hardware probe
          </button>
          {probe.isError ? <p role="alert" className="text-xs text-fail">{probe.error.message}</p> : null}
        </div>
      )}

      {sug ? (
        <div>
          <p className="mb-1 text-xs" data-testid="default-tier">
            Suggested tier: <strong>{sug.default_tier}</strong>
            {sug.default_reason ? ` (${sug.default_reason})` : ""}
          </p>
          <div role="radiogroup" aria-label="Model tier" className="mb-2 flex flex-wrap gap-1" onKeyDown={onKeyDown}>
            {TIERS.map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={tier === t}
                tabIndex={tier === t ? 0 : -1}
                data-tier={t}
                onClick={() => setPicked(t)}
                className={`min-h-[2rem] rounded-lg px-2.5 text-xs ring-1 ring-inset ${FOCUS} ${
                  tier === t ? "bg-ink font-semibold text-raised ring-ink" : "bg-raised text-ink ring-line hover:bg-sunk"
                }`}
              >
                {t}
                {t === sug.default_tier ? " (suggested)" : ""}
              </button>
            ))}
          </div>
          <table className="w-full text-left text-xs" data-testid="tier-table">
            <thead>
              <tr>
                <th scope="col" className="pb-1 pr-1 font-medium text-muted">Task</th>
                <th scope="col" className="pb-1 pr-1 font-medium text-muted">Model</th>
                <th scope="col" className="pb-1 pr-1 font-medium text-muted">Fits</th>
                <th scope="col" className="pb-1 pr-1 font-medium text-muted">Speed</th>
                <th scope="col" className="pb-1 font-medium text-muted">Pulled</th>
              </tr>
            </thead>
            <tbody>
              {sug.rows.map((r) => {
                const o = r[tier];
                return (
                  <tr key={r.task}>
                    <th scope="row" className="pr-1 font-normal">{r.task}</th>
                    <td className="break-all pr-1 font-mono text-2xs">{o.model}</td>
                    <td className="pr-1">{o.fits ? "yes" : "no"}</td>
                    <td className="pr-1">{o.speed_class}</td>
                    <td>{o.present ? "yes" : "no"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {cmds.length ? (
            <div className="mt-2">
              <p className="text-xs">Run these yourself to download models (nothing is pulled automatically):</p>
              <pre className="overflow-auto rounded-lg bg-sunk p-2 font-mono text-2xs text-ink ring-1 ring-inset ring-line" data-testid="pull-commands">
                {cmds.join("\n")}
              </pre>
              <button
                type="button"
                onClick={() => void navigator.clipboard?.writeText(cmds.join("\n"))}
                className={`mt-1 min-h-[2rem] rounded-lg border border-line bg-raised px-2.5 text-xs hover:bg-sunk ${FOCUS}`}
              >
                Copy
              </button>
            </div>
          ) : null}
          <Hint id="applyTier">
          <button
            type="button"
            data-testid="apply-tier"
            onClick={() => apply.mutate(tier)}
            disabled={apply.isPending}
            className={`mt-2 min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-3 text-sm font-semibold text-ink hover:bg-sunk disabled:opacity-50 ${FOCUS} focus-visible:ring-offset-2`}
          >
            Apply {tier}
          </button>
          </Hint>
          {apply.isSuccess ? (
            <p role="status" className="mt-1 text-xs text-done-ink" data-testid="apply-result">
              Applied {tier}: {apply.data.stale.length} stage{apply.data.stale.length === 1 ? "" : "s"} will re-run.
            </p>
          ) : null}
          {apply.isError ? (
            <p role="alert" className="mt-1 text-xs text-fail" data-testid="apply-error">
              {apply.error instanceof Error && "detail" in apply.error ? String((apply.error as { detail: string }).detail) : apply.error.message}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
