import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { client, unwrap } from "../api/client";
import type { DocFigure } from "../api/schema";
import { FOCUS } from "./labels";

export const docFiguresKey = (slug: string) => ["docFigures", slug] as const;

interface Props {
  slug: string;
  articleId: string;
  onPick: (fig: DocFigure, alsoDetach: boolean) => void;
  onClose: () => void;
}

export default function FigurePicker({ slug, articleId, onPick, onClose }: Props) {
  const q = useQuery({
    queryKey: docFiguresKey(slug),
    queryFn: async (): Promise<DocFigure[]> => unwrap(await client.GET("/api/docs/{slug}/figures", { params: { path: { slug } } })),
    staleTime: 0,
  });
  const [filter, setFilter] = useState("");
  const [active, setActive] = useState(-1);
  const [alsoDetach, setAlsoDetach] = useState(true);
  const dlg = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => prior?.focus?.();
  }, []);
  const list = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (q.data ?? []).filter((x) => !f || x.figure_id.toLowerCase().includes(f) || (x.record.caption_original ?? "").toLowerCase().includes(f));
  }, [q.data, filter]);

  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(list.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "BUTTON") {
      e.preventDefault();
      const pick = list[active < 0 ? 0 : active];
      if (pick) onPick(pick, alsoDetach);
    } else if (e.key === "Tab") {
      const f = Array.from(dlg.current?.querySelectorAll<HTMLElement>("input, button") ?? []);
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
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        ref={dlg}
        role="dialog"
        aria-modal="true"
        aria-label="Attach a figure"
        data-hotkey-scope="picker"
        data-testid="figure-picker"
        onKeyDown={onKeyDown}
        className="flex max-h-[80vh] w-[34rem] flex-col gap-2 rounded bg-white p-4 shadow-xl"
      >
        <h2 className="text-lg font-semibold">Attach a figure to this article</h2>
        <p className="text-xs text-slate-600">{articleId}</p>
        <input
          ref={input}
          role="combobox"
          aria-expanded="true"
          aria-controls="picker-list"
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 && list[active] ? `pick-${list[active].figure_id}` : undefined}
          aria-label="Filter figures"
          placeholder="Filter by figure id or caption"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setActive(-1);
          }}
          className={`rounded border border-slate-400 px-2 py-1 ${FOCUS}`}
        />
        {q.isLoading ? <p role="status" className="p-2 text-sm text-slate-600">Loading figures...</p> : null}
        {q.isError ? <p role="alert" className="p-2 text-sm text-red-800">Could not load figures</p> : null}
        <ul id="picker-list" role="listbox" aria-label="Figures of this document" className="min-h-0 flex-1 overflow-auto">
          {list.map((f, i) => (
            <li
              key={f.figure_id}
              id={`pick-${f.figure_id}`}
              role="option"
              aria-selected={i === active}
              data-testid={`pick-${f.figure_id}`}
              onClick={() => onPick(f, alsoDetach)}
              className={`flex cursor-pointer items-center gap-2 border-b border-slate-100 p-1 text-sm ${i === active ? "bg-blue-100" : "hover:bg-slate-50"}`}
            >
              <img src={`${f.image_url}?v=${f.record.phash}`} alt="" className="h-10 w-10 object-contain" />
              <span className="font-mono text-xs">{f.figure_id}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-slate-700">{f.record.caption_original ?? ""}</span>
              <span className="text-xs text-slate-600">
                {(f.attachments ?? []).length ? (f.attachments ?? []).map((a) => `${a.article_id.split("--").pop()} (${a.rule})`).join(", ") : "unattached"}
              </span>
            </li>
          ))}
        </ul>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={alsoDetach} onChange={(e) => setAlsoDetach(e.target.checked)} className={FOCUS} />
          Also detach from its other articles
        </label>
        <div className="flex justify-end">
          <button type="button" onClick={onClose} className={`rounded border border-slate-500 px-3 py-1 ${FOCUS}`}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
