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
  return (
    <div>
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
      {reason ? (
        <p id="confirm-reason" className="mt-1 text-xs text-slate-600" data-testid="confirm-reason">
          {reason}
        </p>
      ) : null}
    </div>
  );
}
