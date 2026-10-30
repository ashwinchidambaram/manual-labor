import { copyParts, keyLabel } from "./guide";

/** One key drawn as a keycap. Every key the app prints goes through this, so keys never read as bare letters. */
export function Keycap({ children, dark = false }: { children: string; dark?: boolean }) {
  return (
    <kbd
      className={`inline-block min-w-[1.4em] rounded-[5px] border px-1 text-center font-mono text-[0.8em] font-medium leading-tight ${
        dark ? "border-line-strong bg-ink text-raised" : "border-line bg-raised text-ink shadow-key"
      }`}
    >
      {children}
    </kbd>
  );
}

/** Guide copy with `{hotkeyId}` tokens rendered as keycaps from HOTKEYS. */
export default function Copy({ text }: { text: string }) {
  return (
    <>
      {copyParts(text).map((p, i) => ("key" in p ? <Keycap key={i}>{keyLabel(p.key)}</Keycap> : <span key={i}>{p.text}</span>))}
    </>
  );
}
