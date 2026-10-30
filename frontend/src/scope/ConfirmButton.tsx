import Copy from "../onboarding/Copy";
import Hint from "../onboarding/Hint";
import { keyLabel } from "../onboarding/guide";

export default function ConfirmButton({
  blocks,
  processing,
  busy,
  onConfirm,
}: {
  blocks: number;
  processing: boolean;
  busy: boolean;
  onConfirm: () => void;
}) {
  const reason = blocks === 0 ? "Nothing selected" : processing ? "Documents are still being processed" : null;
  // what to do about it, with the keys from HOTKEYS
  const fix =
    blocks === 0
      ? " Select at least one topic or section ({toggleRow} on a row, {selectAll} for all)."
      : processing
        ? " Confirm once every document has finished processing."
        : "";
  return (
    <div>
      {reason ? null : (
        <p className="mb-2 text-center text-xs text-muted max-wide:hidden">Scoring starts and Verify opens straight away.</p>
      )}
      <Hint id="confirm">
      <button
        type="button"
        onClick={onConfirm}
        disabled={reason !== null || busy}
        aria-describedby={reason ? "confirm-reason" : undefined}
        data-testid="confirm"
        className="flex min-h-[3rem] w-full items-center justify-center gap-2.5 rounded-xl bg-act px-4 text-base font-semibold text-act-on transition-colors duration-150 ease-out-quart hover:bg-act-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2"
      >
        Confirm scope and go to Verify
        <kbd aria-hidden="true" className="rounded-md border border-act-line bg-act-hover px-1.5 font-mono text-2xs font-semibold">
          {keyLabel("confirm")}
        </kbd>
      </button>
      </Hint>
      {reason ? (
        <p id="confirm-reason" className="mt-1.5 text-xs text-muted" data-testid="confirm-reason">
          {reason}
          <Copy text={fix} />
        </p>
      ) : null}
    </div>
  );
}
