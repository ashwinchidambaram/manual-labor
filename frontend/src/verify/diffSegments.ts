// Diff rendering model (design 09 section 4). Pure; the 12-row table is unit-tested.
import type { DiffOp } from "../api/schema";

export type SegKind = "equal" | "ins" | "del" | "move";
export interface Segment {
  kind: SegKind;
  ok: boolean;
  /** original text */
  text: string;
  /** visible form: whitespace made visible in non-equal segments (same length as `text`, newline gets a real break when rendered) */
  display: string;
  /** [start, end) ranges of numbers inside `text` */
  numeric: [number, number][];
  opIndex: number;
}

const WS: Record<string, string> = { " ": "␣", "\n": "↵", "\t": "→", " ": "⍽" };

/** Make whitespace visible, one character for one character (so numeric ranges stay valid). */
export function visualize(s: string): string {
  let out = "";
  for (const ch of s) out += WS[ch] ?? ch;
  return out;
}

/** Ranges of numbers such as `10`, `0.25`, `1,250.5`; the digits of `10A` and `4471-A` count. */
export function numericRanges(s: string): [number, number][] {
  const out: [number, number][] = [];
  for (const m of s.matchAll(/\d+(?:[.,]\d+)*/g)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  return out;
}

function seg(kind: SegKind, ok: boolean, text: string, opIndex: number): Segment[] {
  if (text === "") return [];
  return [{ kind, ok, text, display: kind === "equal" ? text : visualize(text), numeric: numericRanges(text), opIndex }];
}

export function diffSegments(ops: DiffOp[]): Segment[] {
  return ops.flatMap((o, i): Segment[] => {
    switch (o.op) {
      case "equal":
        return seg("equal", o.allowed, o.clean, i);
      case "delete":
        return seg("del", o.allowed, o.raw, i);
      case "insert":
        return seg("ins", o.allowed, o.clean, i);
      case "replace":
        return [...seg("del", o.allowed, o.raw, i), ...seg("ins", o.allowed, o.clean, i)];
      case "reorder":
        return seg("move", o.allowed, o.clean !== "" ? o.clean : o.raw, i);
    }
  });
}

/** True when every op is an equal op with identical raw and clean text. */
export const isIdentical = (ops: DiffOp[]): boolean => ops.every((o) => o.op === "equal" && o.raw === o.clean);

export const rawOf = (ops: DiffOp[]): string => ops.map((o) => o.raw).join("");
export const cleanOf = (ops: DiffOp[]): string => ops.map((o) => o.clean).join("");
