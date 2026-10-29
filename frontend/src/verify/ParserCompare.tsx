import type { Block } from "../api/schema";
import { parserDiff, pickPair } from "./parserDiff";

export default function ParserCompare({ texts, block }: { texts: Record<string, string>; block: Block }) {
  const sig = (n: string): number => block.signals?.find((s) => s.name === n)?.value ?? 1;
  if (sig("parser_agreement") >= 1 && sig("textlayer_vs_ocr") >= 1) return null;
  const pair = pickPair(texts);
  if (!pair) return null;
  const d = parserDiff(pair.ta, pair.tb);
  const col = (name: string, spans: { text: string; differs: boolean }[]) => (
    <div className="min-w-0 flex-1">
      <h4 className="text-xs font-semibold uppercase text-slate-600">{name}</h4>
      <p className="whitespace-pre-wrap break-words text-xs">
        {spans.map((s, i) => (s.differs ? <mark key={i} data-testid="parser-diff" className="bg-red-200 text-inherit">{s.text}</mark> : <span key={i}>{s.text}</span>))}
      </p>
    </div>
  );
  return (
    <section aria-label="Parser comparison" className="text-sm" data-testid="parser-compare">
      <h3 className="font-semibold">Where the parsers disagree</h3>
      <div className="mt-1 flex gap-3">
        {col(pair.a, d.a)}
        {col(pair.b, d.b)}
      </div>
    </section>
  );
}
