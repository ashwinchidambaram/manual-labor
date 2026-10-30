import { cloneElement, useCallback, useEffect, useId, useRef, useState, type FocusEvent, type MouseEvent, type ReactElement } from "react";
import { createPortal } from "react-dom";
import { keyLabel } from "./guide";
import { HINTS, type HintId } from "./hints";

// Pointer vs keyboard modality: a focus that follows a click is not a keyboard focus, whatever the browser says.
let pointerFocus = false;
if (typeof document !== "undefined") {
  const pointer = (): void => {
    pointerFocus = true;
  };
  document.addEventListener("pointerdown", pointer, true);
  document.addEventListener("mousedown", pointer, true);
  document.addEventListener("keydown", () => (pointerFocus = false), true);
}

function keyboardFocus(el: Element): boolean {
  if (pointerFocus) return false;
  try {
    return el.matches(":focus-visible");
  } catch {
    return true;
  }
}

const hoverCapable = (): boolean => {
  try {
    return typeof window.matchMedia !== "function" || !window.matchMedia("(hover: none)").matches;
  } catch {
    return true;
  }
};

const DELAY = 400;

interface Pos {
  top: number;
  left: number;
}

/**
 * A tooltip for one trigger (design 12 O4). It never takes focus and registers no hotkey: it opens on hover (after
 * 400 ms) and on keyboard focus, lives in a portal only while open (so it never adds text to the trigger), sets
 * `aria-describedby` only while open, and hides on Esc through a passive listener that leaves the event to the app.
 * `within`: the trigger is a group (a radiogroup); focus on any control inside it shows the hint.
 */
export default function Hint({ id, children, text, within = false }: { id: HintId; children: ReactElement; text?: string; within?: boolean }) {
  const tipId = useId();
  const [pos, setPos] = useState<Pos | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const anchor = useRef<Element | null>(null);
  const entry = HINTS[id] as { text: string; hotkey?: Parameters<typeof keyLabel>[0] };

  const clear = (): void => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const show = useCallback((el: Element) => {
    anchor.current = el;
    const r = el.getBoundingClientRect();
    const vw = window.innerWidth || 1024;
    const vh = window.innerHeight || 768;
    const below = r.bottom + 8;
    const top = below + 64 > vh && r.top > 80 ? Math.max(4, r.top - 8 - 64) : below;
    setPos({ top, left: Math.max(8, Math.min(r.left, vw - 296)) });
  }, []);
  const hide = useCallback(() => {
    clear();
    setPos(null);
  }, []);
  useEffect(() => () => clear(), []);
  useEffect(() => {
    if (!pos) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") hide();
    };
    // a scroll (often the browser bringing the focused trigger into view) moves the bubble with it; it hides only
    // once the trigger has left the viewport
    const onScroll = (): void => {
      const el = anchor.current;
      if (!el || !el.isConnected) return hide();
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > (window.innerHeight || 768)) hide();
      else show(el);
    };
    document.addEventListener("keydown", onKey, { capture: true, passive: true });
    window.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => {
      document.removeEventListener("keydown", onKey, { capture: true });
      window.removeEventListener("scroll", onScroll, { capture: true });
    };
  }, [pos, hide, show]);

  const p = children.props as Record<string, unknown>;
  const call = (name: string, e: unknown): void => {
    const f = p[name];
    if (typeof f === "function") (f as (ev: unknown) => void)(e);
  };
  const open = pos !== null;
  const described = [p["aria-describedby"] as string | undefined, open ? tipId : undefined].filter(Boolean).join(" ") || undefined;
  const trigger = cloneElement(children, {
    "aria-describedby": described,
    onMouseEnter: (e: MouseEvent) => {
      call("onMouseEnter", e);
      if (!hoverCapable()) return;
      const el = e.currentTarget;
      clear();
      timer.current = setTimeout(() => show(el), DELAY);
    },
    onMouseLeave: (e: MouseEvent) => {
      call("onMouseLeave", e);
      if (anchor.current && document.activeElement === anchor.current && keyboardFocus(anchor.current)) return;
      hide();
    },
    onFocus: (e: FocusEvent) => {
      call("onFocus", e);
      const self = e.target === e.currentTarget;
      if ((self || within) && keyboardFocus(e.target)) show(e.currentTarget);
    },
    onBlur: (e: FocusEvent) => {
      call("onBlur", e);
      if (within && e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget)) return;
      hide();
    },
  });
  const key = entry.hotkey ? keyLabel(entry.hotkey) : null;
  return (
    <>
      {trigger}
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              role="tooltip"
              id={tipId}
              data-testid="hint"
              data-hint={id}
              style={{ top: pos.top, left: pos.left }}
              className="pointer-events-none fixed z-[60] max-w-[18rem] rounded-md bg-slate-900 px-2.5 py-1.5 text-xs leading-snug text-slate-50 shadow-lg"
            >
              {text ?? entry.text}
              {key ? (
                <span className="ml-1.5 whitespace-nowrap text-slate-300">
                  Key <kbd className="rounded border border-slate-600 px-1 font-mono text-[0.7rem] text-slate-50">{key}</kbd>
                </span>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
