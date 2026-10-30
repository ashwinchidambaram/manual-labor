/**
 * "Needs you" mark: a drawn exclamation in a ring, so no "!" character ever reaches the page text (the copy rule is no
 * exclamation marks). Decorative: every use sits next to words that say the same.
 */
export function AttentionIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" className={`inline-block h-[1em] w-[1em] ${className}`}>
      <circle cx="8" cy="8" r="6.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="7.25" y="4" width="1.5" height="5" rx="0.75" fill="currentColor" />
      <circle cx="8" cy="11.25" r="0.95" fill="currentColor" />
    </svg>
  );
}
