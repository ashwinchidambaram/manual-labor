import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { client, unwrap } from "../api/client";
import { trackJob } from "../api/queries";
import type { LearningUse } from "../api/schema";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "../shell/Toast";
import Hint from "../onboarding/Hint";
import { FOCUS } from "./labels";

export default function LearningChip({ learning, slug }: { learning: LearningUse; slug: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [changed, setChanged] = useState(false);
  const rules = learning.learned_rules ?? [];
  const shots = learning.few_shot ?? [];
  const disable = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await client.POST("/api/learning/items/{item_id}/disable", { params: { path: { item_id: id } }, body: { request_id: crypto.randomUUID() } })),
    onSuccess: () => setChanged(true),
    onError: (e) => toast.error(`Could not disable: ${(e as Error).message}`),
  });
  const rerun = useMutation({
    mutationFn: async () => unwrap(await client.POST("/api/jobs", { body: { to: "score2", docs: [slug], allow_reparse: false } })),
    onSuccess: (job) => trackJob(qc, job),
  });
  if (rules.length + shots.length === 0) return null;
  return (
    <section aria-label="Learning" className="text-sm" data-testid="learning-chip">
      <Hint id="learningChip">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`rounded-full border border-violet-400 bg-violet-50 px-3 py-0.5 text-violet-900 ${FOCUS}`}
      >
        Why did this change? learned ({learning.provenance})
      </button>
      </Hint>
      {open ? (
        <ul className="mt-1 space-y-1">
          {[...rules, ...shots].map((id) => (
            <li key={id} className="flex items-center gap-2">
              <span className="font-mono text-xs">{id}</span>
              <button
                type="button"
                onClick={() => disable.mutate(id)}
                disabled={disable.isPending}
                className={`rounded border border-slate-400 px-2 text-xs ${FOCUS}`}
                aria-label={`Disable ${id}`}
              >
                Disable
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {changed ? (
        <p role="status" className="mt-1 flex items-center gap-2" data-testid="learning-notice">
          Learning updated. Re-run cleanup to apply
          <button type="button" onClick={() => rerun.mutate()} className={`rounded border border-slate-400 px-2 text-xs ${FOCUS}`}>
            Re-run cleanup
          </button>
        </p>
      ) : null}
    </section>
  );
}
