import { Fragment } from "react";
import type { DiffOp } from "../api/schema";
import { diffSegments, isIdentical, type Segment } from "./diffSegments";

/** Text with numbers emphasised; `breaks` adds a real line break after each visible newline mark. */
export function Marked({ text, ranges, breaks = false }: { text: string; ranges: [number, number][]; breaks?: boolean }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  const plain = (s: string, key: string): void => {
    if (!s) return;
    if (!breaks || !s.includes("↵")) {
      parts.push(<Fragment key={key}>{s}</Fragment>);
      return;
    }
    s.split("↵").forEach((piece, i, arr) => {
      parts.push(
        <Fragment key={`${key}-${i}`}>
          {piece}
          {i < arr.length - 1 ? (
            <>
              ↵<br />
            </>
          ) : null}
        </Fragment>,
      );
    });
  };
  ranges.forEach(([a, b], i) => {
    plain(text.slice(at, a), `p${i}`);
    parts.push(
      <mark key={`n${i}`} className="num bg-transparent font-bold text-inherit">
        {text.slice(a, b)}
      </mark>,
    );
    at = b;
  });
  plain(text.slice(at), "tail");
  return <>{parts}</>;
}

const CLS: Record<string, string> = {
  equal: "",
  "del-ok": "text-slate-500 line-through",
  "del-bad": "font-bold text-red-700 line-through",
  "ins-ok": "text-slate-500 underline",
  "ins-bad": "font-bold text-red-700 underline",
  "move-ok": "text-blue-700 before:content-['⇅'] before:mr-0.5",
  "move-bad": "text-red-700 before:content-['⇅'] before:mr-0.5",
};
const TITLE: Record<string, string | undefined> = {
  "del-bad": "removed",
  "ins-bad": "added",
  "move-ok": "moved (reading order)",
  "move-bad": "moved (reading order)",
};

export const segName = (s: Segment): string => (s.kind === "equal" ? "equal" : `${s.kind}-${s.ok ? "ok" : "bad"}`);

function SegSpan({ s }: { s: Segment }) {
  const name = segName(s);
  const label = s.kind === "del" ? `removed: ${s.text}` : s.kind === "ins" ? `inserted: ${s.text}` : undefined;
  const props = {
    "data-op-index": s.opIndex,
    "data-seg": name,
    title: TITLE[name],
    "aria-label": label,
    className: CLS[name],
  };
  const inner = <Marked text={s.display} ranges={s.numeric} breaks={s.kind !== "equal"} />;
  if (s.kind === "del") return <del {...props}>{inner}</del>;
  if (s.kind === "ins") return <ins {...props}>{inner}</ins>;
  return <span {...props}>{inner}</span>;
}

export default function DiffView({ ops }: { ops: DiffOp[] }) {
  if (isIdentical(ops)) return <p data-testid="diff-identical" className="text-sm text-slate-600">Identical to raw</p>;
  const segs = diffSegments(ops);
  return (
    <div>
      <div data-testid="diff-view" className="whitespace-pre-wrap break-words text-sm leading-relaxed">
        {segs.map((s, i) => (
          <SegSpan key={i} s={s} />
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-600" data-testid="diff-legend">
        Legend: <del className="text-slate-500">removed</del> <ins className="text-slate-500">added</ins>{" "}
        <del className="font-bold text-red-700">removed (changes content)</del> <ins className="font-bold text-red-700">added (changes content)</ins>{" "}
        <span className="text-blue-700 before:content-['⇅']">moved</span>; spaces show as ␣ and line breaks as ↵
      </p>
    </div>
  );
}
