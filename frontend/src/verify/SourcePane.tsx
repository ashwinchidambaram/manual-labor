import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { client, unwrap } from "../api/client";
import type { BlockDetail, PageBlock, PageRef } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { FOCUS } from "./labels";
import { disagreeWords, mapToOcrWords, pickPair } from "./parserDiff";
import { moveCorner, pointStyle, rectStyle, type BBox, type Corner } from "./geometry";
import { pageBlocksKey } from "./useVerifyState";

export interface CropState {
  box: BBox;
  onChange: (b: BBox) => void;
}

interface Props {
  page: PageRef;
  /** the block whose detail is shown (highlight and disagreement words) */
  detail: BlockDetail | null;
  currentId: string | null;
  zoom: boolean;
  onJump: (id: string) => void;
  crop?: CropState | null;
}

const CORNERS: { id: Corner; label: string; xi: 0 | 2; yi: 1 | 3 }[] = [
  { id: "nw", label: "top left", xi: 0, yi: 1 },
  { id: "ne", label: "top right", xi: 2, yi: 1 },
  { id: "sw", label: "bottom left", xi: 0, yi: 3 },
  { id: "se", label: "bottom right", xi: 2, yi: 3 },
];

export default function SourcePane({ page, detail, currentId, zoom, onJump, crop }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const blocksQ = useQuery({
    queryKey: pageBlocksKey(page.doc_id, page.page),
    queryFn: async (): Promise<PageBlock[]> =>
      unwrap(await client.GET("/api/docs/{slug}/pages/{page}/blocks", { params: { path: { slug: page.doc_id, page: page.page } } })),
    staleTime: Infinity,
    enabled: page.width > 0,
  });
  const rects = useMemo(() => (blocksQ.data ?? []).filter((b) => b.bbox.length === 4), [blocksQ.data]);

  const own = detail && detail.page.doc_id === page.doc_id && detail.page.page === page.page ? detail.block : null;
  const words = useMemo(() => {
    if (!own) return { boxes: [] as number[][], whole: false };
    const pair = pickPair(own.raw_text_by_parser ?? {});
    if (!pair || pair.ta === pair.tb) return { boxes: [], whole: false };
    const ocr = own.ocr_words ?? [];
    const hits = mapToOcrWords(disagreeWords(pair.ta, pair.tb), ocr);
    return { boxes: hits.map((h) => h.bbox as number[]), whole: hits.length === 0 };
  }, [own]);

  useEffect(() => {
    if (!currentId || crop) return;
    wrap.current?.querySelector<HTMLElement>("[data-current='true']")?.scrollIntoView?.({ block: "center", inline: "nearest" });
  }, [currentId, rects.length, page.page, crop]);

  const focusable = rects.filter((r) => r.type !== "header" && r.type !== "footer");
  const move = (d: 1 | -1): void => {
    const active = document.activeElement as HTMLElement | null;
    const i = focusable.findIndex((r) => `rect-${r.block_id}` === active?.getAttribute("data-testid"));
    const j = Math.min(focusable.length - 1, Math.max(0, (i < 0 ? focusable.findIndex((r) => r.block_id === currentId) : i) + d));
    const target = focusable[j];
    if (target) wrap.current?.querySelector<HTMLElement>(`[data-testid='rect-${target.block_id}']`)?.focus();
  };
  useHotkeys({ vSrcNext: () => move(1), vSrcPrev: () => move(-1) });

  if (page.render_url === null)
    return (
      <section role="region" aria-label="Source page" className="min-h-0 overflow-auto p-3 text-sm" data-zone="source">
        <p data-testid="no-page-image" className="rounded bg-slate-100 p-2">
          No page image for Word documents
        </p>
        {detail ? <pre className="mt-2 whitespace-pre-wrap font-sans">{detail.block.raw_text}</pre> : null}
      </section>
    );

  const src = `${page.render_url}?dpi=${zoom ? 300 : 150}`;
  const onHandleKey = (e: React.KeyboardEvent, c: Corner): void => {
    if (!crop) return;
    const step = e.shiftKey ? 10 : 1;
    const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    const m = d[e.key];
    if (!m) return;
    e.preventDefault();
    e.stopPropagation();
    crop.onChange(moveCorner(crop.box, c, m[0], m[1], page));
  };
  const onHandlePointer = (e: React.PointerEvent<HTMLButtonElement>, c: Corner): void => {
    if (!crop || !wrap.current) return;
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    const px = wrap.current.getBoundingClientRect().width / page.width;
    let box = crop.box;
    let lx = e.clientX;
    let ly = e.clientY;
    const move = (ev: PointerEvent): void => {
      box = moveCorner(box, c, (ev.clientX - lx) / px, (ev.clientY - ly) / px, page);
      lx = ev.clientX;
      ly = ev.clientY;
      crop.onChange(box);
    };
    const up = (): void => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
  };

  return (
    <section role="region" aria-label="Source page" className="min-h-0 overflow-auto bg-slate-100 p-2" data-zone="source" data-testid="source-pane">
      <div ref={wrap} className="relative" style={{ width: zoom ? "200%" : "100%" }}>
        <img src={src} alt={`Page ${page.page} of ${page.doc_id}`} className="block w-full select-none bg-white" draggable={false} />
        {page.width > 0 && !crop
          ? rects.map((r) => {
              const isHF = r.type === "header" || r.type === "footer";
              const cur = r.block_id === currentId;
              return (
                <button
                  key={r.block_id}
                  type="button"
                  disabled={isHF}
                  tabIndex={cur ? 0 : -1}
                  data-testid={`rect-${r.block_id}`}
                  data-current={cur ? "true" : undefined}
                  aria-label={`${r.type} block ${r.block_id}, ${r.status}`}
                  onClick={() => onJump(r.block_id)}
                  style={{ position: "absolute", ...rectStyle(r.bbox, page) }}
                  className={`${FOCUS} ${
                    isHF
                      ? "cursor-default border border-dashed border-slate-400"
                      : cur
                        ? "border-2 border-blue-600 bg-blue-500/10"
                        : "border border-slate-500/40 hover:bg-blue-500/10"
                  }`}
                />
              );
            })
          : null}
        {page.width > 0 && !crop && own?.bbox && words.whole ? (
          <div
            data-testid="disagree-block"
            title="parsers disagree"
            style={{ position: "absolute", pointerEvents: "none", ...rectStyle(own.bbox, page), backgroundImage: "repeating-linear-gradient(45deg, rgba(220,38,38,.25) 0 4px, transparent 4px 8px)" }}
          />
        ) : null}
        {page.width > 0 && !crop
          ? words.boxes.map((b, i) => (
              <div
                key={i}
                data-testid="disagree-word"
                style={{ position: "absolute", pointerEvents: "none", ...rectStyle(b, page) }}
                className="bg-red-500/30 outline outline-1 outline-red-600"
              />
            ))
          : null}
        {crop && page.width > 0 ? (
          <>
            <div
              data-testid="crop-box"
              style={{ position: "absolute", pointerEvents: "none", ...rectStyle(crop.box, page) }}
              className="border-2 border-emerald-600 bg-emerald-500/10"
            />
            {CORNERS.map((c) => (
              <button
                key={c.id}
                type="button"
                aria-label={`Crop handle ${c.label}`}
                data-testid={`crop-handle-${c.id}`}
                onKeyDown={(e) => onHandleKey(e, c.id)}
                onPointerDown={(e) => onHandlePointer(e, c.id)}
                style={{ position: "absolute", transform: "translate(-50%, -50%)", ...pointStyle(crop.box[c.xi], crop.box[c.yi], page) }}
                className={`h-4 w-4 cursor-move rounded-full border-2 border-white bg-emerald-600 ${FOCUS}`}
              />
            ))}
          </>
        ) : null}
      </div>
    </section>
  );
}
