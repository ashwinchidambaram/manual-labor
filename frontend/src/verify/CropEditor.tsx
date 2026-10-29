import { useEffect, useRef } from "react";
import type { PageRef } from "../api/schema";
import { validCrop, type BBox } from "./geometry";
import { FOCUS } from "./labels";

interface Props {
  figureId: string;
  box: BBox | null;
  page: PageRef | null;
  onChange: (b: BBox) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}

export default function CropEditor({ figureId, box, page, onChange, onSave, onCancel, busy }: Props) {
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
  const err = box && page ? validCrop(box, page) : null;
  const names = ["x0", "y0", "x1", "y1"] as const;
  return (
    <form
      aria-label={`Crop ${figureId}`}
      data-testid="crop-editor"
      onSubmit={(e) => {
        e.preventDefault();
        if (!err && box) onSave();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onCancel();
        }
      }}
      className="space-y-2 border-t border-slate-300 bg-white p-2 text-sm"
    >
      <h3 className="font-semibold">Crop {figureId}</h3>
      {box === null ? (
        <p>Word images have no crop box</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2">
            {names.map((n, i) => (
              <label key={n} className="flex flex-col text-xs">
                {n} (pt)
                <input
                  ref={i === 0 ? first : undefined}
                  type="number"
                  step="0.5"
                  aria-label={n}
                  value={Number.isFinite(box[i]) ? box[i] : ""}
                  onChange={(e) => {
                    const next = [...box] as BBox;
                    next[i] = e.target.value === "" ? NaN : Number(e.target.value);
                    onChange(next);
                  }}
                  className={`rounded border border-slate-400 px-1 py-0.5 ${FOCUS}`}
                />
              </label>
            ))}
          </div>
          {err ? (
            <p role="alert" data-testid="crop-error" className="text-red-800">
              {err}
            </p>
          ) : null}
        </>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || err !== null || box === null} className={`rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50 ${FOCUS}`}>
          Save crop
        </button>
        <button type="button" onClick={onCancel} className={`rounded border border-slate-500 px-3 py-1 ${FOCUS}`}>
          Cancel
        </button>
      </div>
    </form>
  );
}
