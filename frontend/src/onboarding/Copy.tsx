import { copyParts, keyLabel } from "./guide";

/** Guide copy with `{hotkeyId}` tokens rendered as <kbd> keys from HOTKEYS. */
export default function Copy({ text }: { text: string }) {
  return (
    <>
      {copyParts(text).map((p, i) =>
        "key" in p ? (
          <kbd key={i} className="rounded border border-slate-300 bg-slate-50 px-1 font-mono text-[0.8em] text-slate-900">
            {keyLabel(p.key)}
          </kbd>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
