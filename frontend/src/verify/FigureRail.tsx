import Hint from "../onboarding/Hint";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, client, unwrap } from "../api/client";
import { trackJob } from "../api/queries";
import type { BlockDetail, DocFigure, FigureRailItem } from "../api/schema";
import { useJobWatch } from "../hooks/useJobsPolling";
import { useHotkeys } from "../hooks/useHotkeys";
import { useToast } from "../shell/Toast";
import FigurePicker from "./FigurePicker";
import { FOCUS } from "./labels";

/** finite on purpose: a rail left behind while a job ran must refetch when it is shown again */
const RAIL_STALE_MS = 30_000;
export const railKey = (articleId: string) => ["rail", articleId] as const;
const INVALIDATE: readonly (readonly string[])[] = [["rail"], ["docFigures"], ["verify"], ["pageBlocks"]];

interface SectionApi {
  detach: (figureId: string) => void;
  crop: (figureId: string) => void;
}

interface Overlay {
  figureId: string;
  kind: "add" | "remove";
  item?: FigureRailItem;
  jobId: string | null;
}

function JobWatch({ id, onSettled }: { id: string; onSettled: (ok: boolean, error: string | null) => void }) {
  const q = useJobWatch(id);
  const status = q.data?.status;
  useEffect(() => {
    if (status === "done") onSettled(true, null);
    else if (status === "failed" || status === "cancelled" || status === "interrupted") onSettled(false, q.data?.error ?? status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  return null;
}

interface SectionProps {
  articleId: string;
  detail: BlockDetail;
  enqueue: <T>(run: () => Promise<T>) => Promise<T>;
  onCrop: (item: FigureRailItem) => void;
  register: (articleId: string, api: SectionApi | null) => void;
}

function RailSection({ articleId, detail, enqueue, onCrop, register }: SectionProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: railKey(articleId),
    queryFn: async (): Promise<FigureRailItem[]> =>
      unwrap(await client.GET("/api/articles/{article_id}/figures", { params: { path: { article_id: articleId } } })),
    staleTime: RAIL_STALE_MS,
  });
  const [overlay, setOverlay] = useState<Overlay[]>([]);
  const [picking, setPicking] = useState(false);
  const block = detail.block;
  const slug = block.doc_id;

  const items = (() => {
    const base = (q.data ?? []).filter((i) => !overlay.some((o) => o.kind === "add" && o.figureId === i.figure_id));
    const added = overlay.filter((o) => o.kind === "add" && o.item).map((o) => o.item!);
    return [...base, ...added];
  })();
  const pendingIds = new Set(overlay.map((o) => o.figureId));

  const settle = (figureId: string, jobId: string) => async (ok: boolean, error: string | null) => {
    if (!ok) toast.error(`Figure change failed: ${error ?? "job failed"}`);
    await Promise.all(INVALIDATE.map((k) => qc.invalidateQueries({ queryKey: k })));
    setOverlay((o) => o.filter((x) => !(x.figureId === figureId && x.jobId === jobId)));
  };
  const call = async (op: "attach" | "detach", figureId: string, art: string, anchor: string | null): Promise<string | null> => {
    try {
      const out = await enqueue(async () =>
        unwrap(
          await client.POST(op === "attach" ? "/api/figures/{fid}/attach" : "/api/figures/{fid}/detach", {
            params: { path: { fid: figureId } },
            body: { article_id: art, anchor_block_id: anchor, request_id: crypto.randomUUID() },
          }),
        ),
      );
      // the app-wide jobs poller reconciles the rail even when this section has unmounted by the time the job ends
      trackJob(qc, out.job);
      return out.job.id;
    } catch (e) {
      toast.error(`Could not ${op} ${figureId}: ${e instanceof ApiError ? e.detail : "network error"}`);
      return null;
    }
  };

  const attach = async (f: DocFigure, alsoDetach: boolean): Promise<void> => {
    setPicking(false);
    const anchor = block.type === "figure" ? null : block.id;
    const item: FigureRailItem = {
      figure_id: f.figure_id,
      block_id: f.block_id,
      record: f.record,
      image_url: f.image_url,
      attachment: { article_id: articleId, rule: "human", confidence: 1, anchor_block_id: anchor },
      status: f.status,
    };
    setOverlay((o) => [...o.filter((x) => x.figureId !== f.figure_id), { figureId: f.figure_id, kind: "add", item, jobId: null }]);
    const jobId = await call("attach", f.figure_id, articleId, anchor);
    if (jobId === null) {
      setOverlay((o) => o.filter((x) => x.figureId !== f.figure_id));
      return;
    }
    setOverlay((o) => o.map((x) => (x.figureId === f.figure_id && x.jobId === null ? { ...x, jobId } : x)));
    if (alsoDetach)
      for (const a of (f.attachments ?? []).filter((x) => x.article_id !== articleId)) await call("detach", f.figure_id, a.article_id, null);
  };
  const detach = async (item: FigureRailItem): Promise<void> => {
    setOverlay((o) => [...o.filter((x) => x.figureId !== item.figure_id), { figureId: item.figure_id, kind: "remove", jobId: null }]);
    const jobId = await call("detach", item.figure_id, articleId, null);
    if (jobId === null) setOverlay((o) => o.filter((x) => x.figureId !== item.figure_id));
    else setOverlay((o) => o.map((x) => (x.figureId === item.figure_id && x.jobId === null ? { ...x, jobId } : x)));
  };

  useEffect(() => {
    register(articleId, {
      detach: (id) => {
        const it = items.find((i) => i.figure_id === id);
        if (it) void detach(it);
      },
      crop: (id) => {
        const it = items.find((i) => i.figure_id === id);
        if (it) onCrop(it);
      },
    });
    return () => register(articleId, null);
  });

  return (
    <section aria-label={`Figures in ${articleId}`} className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 text-sm text-ink">
          In the article <span className="font-mono text-2xs text-muted">{articleId}</span>
        </p>
        <Hint id="attachFigure">
          <button
            type="button"
            data-rail-focusable
            data-testid="rail-attach"
            onClick={() => setPicking(true)}
            className={`min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-3 text-sm font-medium text-ink hover:bg-sunk ${FOCUS}`}
          >
            Attach a figure…
          </button>
        </Hint>
      </div>
      <ul role="list" aria-label="Figures in this article" className="space-y-2.5">
        {items.map((it) => {
          const removed = overlay.some((o) => o.kind === "remove" && o.figureId === it.figure_id);
          const pending = pendingIds.has(it.figure_id);
          return (
            <li
              key={it.figure_id}
              data-testid={`rail-item-${it.figure_id}`}
              data-figure-id={it.figure_id}
              data-article-id={articleId}
              data-rail-focusable
              tabIndex={-1}
              className={`grid grid-cols-[5.5rem_1fr] gap-3 rounded-xl border border-line bg-raised p-2.5 text-xs ${FOCUS} ${removed ? "opacity-40" : ""}`}
            >
              <img
                src={`${it.image_url}?v=${it.record.phash}`}
                alt={it.record.caption_original ?? it.figure_id}
                className="max-h-24 w-full rounded-md bg-page object-contain ring-1 ring-inset ring-line-soft"
              />
              <div className="min-w-0 space-y-1">
                {it.record.caption_original ? <div className="manual-text line-clamp-2 text-sm text-ink">{it.record.caption_original}</div> : null}
                <div className="font-mono text-2xs text-muted">{it.figure_id}</div>
                <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-muted">
                  <Hint id="methodBadge">
                    <span>{it.record.extraction}</span>
                  </Hint>
                  <span aria-hidden="true">·</span>
                  <Hint id="attachRule">
                    <span data-testid="rail-rule" className="font-medium text-ink">
                      {it.attachment?.rule ?? "unattached"}
                    </span>
                  </Hint>
                  {it.attachment?.confidence !== undefined && it.attachment?.confidence !== null ? (
                    <span className="tabular-nums">match {it.attachment.confidence.toFixed(2)}</span>
                  ) : null}
                  <span>{it.status}</span>
                  {pending ? (
                    <span data-testid="rail-pending" className="font-semibold text-needs-ink">
                      updating
                    </span>
                  ) : null}
                </div>
                <div className="flex gap-1.5 pt-0.5">
                  <button type="button" className={`min-h-[1.75rem] rounded-md border border-line-strong px-2 text-ink hover:bg-sunk ${FOCUS}`} onClick={() => void detach(it)} aria-label={`Detach ${it.figure_id}`}>
                    Detach (x)
                  </button>
                  <button type="button" className={`min-h-[1.75rem] rounded-md border border-line-strong px-2 text-ink hover:bg-sunk ${FOCUS}`} onClick={() => onCrop(it)} aria-label={`Crop ${it.figure_id}`}>
                    Crop (c)
                  </button>
                </div>
              </div>
            </li>
          );
        })}
        {q.isSuccess && items.length === 0 ? (
          <li className="rounded-xl border border-dashed border-line-strong px-3.5 py-3 text-sm text-muted">
            No figures attached. If this article needs one from the manual, choose Attach a figure.
          </li>
        ) : null}
      </ul>
      {overlay.filter((o) => o.jobId).map((o) => (
        <JobWatch key={`${o.figureId}-${o.jobId}`} id={o.jobId!} onSettled={(ok, err) => void settle(o.figureId, o.jobId!)(ok, err)} />
      ))}
      {picking ? <FigurePicker slug={slug} articleId={articleId} onPick={(f, d) => void attach(f, d)} onClose={() => setPicking(false)} /> : null}
    </section>
  );
}

interface Props {
  detail: BlockDetail | undefined;
  enqueue: SectionProps["enqueue"];
  onCrop: (item: FigureRailItem) => void;
}

export default function FigureRail({ detail, enqueue, onCrop }: Props) {
  const apis = useRef(new Map<string, SectionApi>());
  const register = useCallback((id: string, api: SectionApi | null) => {
    if (api) apis.current.set(id, api);
    else apis.current.delete(id);
  }, []);
  const move = (d: 1 | -1): void => {
    const all = Array.from(document.querySelectorAll<HTMLElement>("[data-zone='rail'] [data-rail-focusable]"));
    const i = all.indexOf(document.activeElement as HTMLElement);
    all[Math.min(all.length - 1, Math.max(0, i + d))]?.focus();
  };
  const focused = (): { fig: string; art: string } | null => {
    const el = (document.activeElement as HTMLElement | null)?.closest<HTMLElement>("[data-figure-id]");
    return el?.dataset.figureId && el.dataset.articleId ? { fig: el.dataset.figureId, art: el.dataset.articleId } : null;
  };
  useHotkeys({
    vRailNext: () => move(1),
    vRailPrev: () => move(-1),
    vRailDetach: () => {
      const f = focused();
      if (f) apis.current.get(f.art)?.detach(f.fig);
    },
    vRailCrop: () => {
      const f = focused();
      if (f) apis.current.get(f.art)?.crop(f.fig);
    },
  });
  return (
    <aside aria-label="Figure rail" data-zone="rail" data-testid="figure-rail" className="space-y-3">
      <h3 className="text-2xs font-semibold uppercase tracking-[0.07em] text-muted">Figures</h3>
      {detail && (detail.article_ids ?? []).length > 0 ? (
        (detail.article_ids ?? []).map((a) => <RailSection key={a} articleId={a} detail={detail} enqueue={enqueue} onCrop={onCrop} register={register} />)
      ) : (
        <p className="text-sm text-muted">{detail ? "This block is not in an article" : ""}</p>
      )}
    </aside>
  );
}
