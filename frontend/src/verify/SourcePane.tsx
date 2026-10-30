import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { client, unwrap } from "../api/client";
import type { BlockDetail, PageBlock, PageRef } from "../api/schema";
import { useHotkeys } from "../hooks/useHotkeys";
import { FOCUS } from "./labels";
import { pageMarks } from "./pageMarks";
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

  // paint order: largest first, so a block inside a table or figure is later in the DOM, on top, and receives the click
  const painted = useMemo(() => {
    const area = (b: number[]): number => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
    return rects.map((r, i) => ({ r, i })).sort((a, b) => area(b.r.bbox) - area(a.r.bbox) || a.i - b.i).map((x) => x.r);
  }, [rects]);

  const own = detail && detail.page.doc_id === page.doc_id && detail.page.page === page.page ? detail.block : null;
  const words = useMemo(() => pageMarks(own), [own]);

  // only the whole-page view scrolls to the block; the small locator never moves the screen
  useEffect(() => {
    if (!currentId || crop || !zoom) return;
    wrap.current?.querySelector<HTMLElement>("[data-current='true']")?.scrollIntoView?.({ block: "center", inline: "nearest" });
  }, [currentId, rects.length, page.page, crop, zoom]);

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
      <section role="region" aria-label="Source page" className="min-h-0 overflow-auto text-sm" data-zone="source">
        <p data-testid="no-page-image" className="rounded-lg bg-raised px-3 py-2 text-muted ring-1 ring-inset ring-line">
          No page image for Word documents
        </p>
        {detail ? <pre className="manual-text mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-sm text-ink">{detail.block.raw_text}</pre> : null}
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
    <section
      role="region"
      aria-label="Source page"
      className={`min-h-0 rounded-lg border border-line bg-page ${zoom || crop ? "max-h-[min(60vh,40rem)] overflow-auto shadow-lift" : "overflow-hidden"}`}
      data-zone="source"
      data-testid="source-pane"
    >
      <div ref={wrap} className="relative w-full">
        <img src={src} alt={`Page ${page.page} of ${page.doc_id}`} className="block w-full select-none bg-page" draggable={false} />
        {page.width > 0 && !crop
          ? painted.map((r) => {
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
                      ? "cursor-default border border-dashed border-line"
                      : cur
                        ? "border-2 border-act bg-[rgb(173_72_40/0.08)]"
                        : "border border-[rgb(134_127_119/0.45)] hover:bg-[rgb(173_72_40/0.08)]"
                  }`}
                />
              );
            })
          : null}
        {page.width > 0 && !crop && own?.bbox && words.whole ? (
          <div
            data-testid="disagree-block"
            title="parsers disagree"
            style={{ position: "absolute", pointerEvents: "none", ...rectStyle(own.bbox, page), backgroundImage: "repeating-linear-gradient(45deg, rgb(238 192 91 / 0.5) 0 4px, transparent 4px 8px)" }}
          />
        ) : null}
        {page.width > 0 && !crop
          ? words.boxes.map((b, i) => (
              <div
                key={i}
                data-testid="disagree-word"
                style={{ position: "absolute", pointerEvents: "none", ...rectStyle(b, page) }}
                className="bg-[rgb(238_192_91/0.5)] outline outline-1 outline-needs-ink"
              />
            ))
          : null}
        {crop && page.width > 0 ? (
          <>
            <div
              data-testid="crop-box"
              style={{ position: "absolute", pointerEvents: "none", ...rectStyle(crop.box, page) }}
              className="border-2 border-act bg-[rgb(173_72_40/0.08)]"
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
                className={`h-4 w-4 cursor-move rounded-full border-2 border-raised bg-act ${FOCUS}`}
              />
            ))}
          </>
        ) : null}
      </div>
    </section>
  );
}
