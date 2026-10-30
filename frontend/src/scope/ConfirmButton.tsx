import Copy from "../onboarding/Copy";
import Hint from "../onboarding/Hint";

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
      <Hint id="confirm">
      <button
        type="button"
        onClick={onConfirm}
        disabled={reason !== null || busy}
        aria-describedby={reason ? "confirm-reason" : undefined}
        data-testid="confirm"
        className="w-full rounded bg-blue-700 px-3 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
      >
        Confirm scope and go to Verify
      </button>
      </Hint>
      {reason ? (
        <p id="confirm-reason" className="mt-1 text-xs text-slate-600" data-testid="confirm-reason">
          {reason}
          <Copy text={fix} />
        </p>
      ) : null}
    </div>
  );
}
