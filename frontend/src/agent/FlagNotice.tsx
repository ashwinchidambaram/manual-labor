// The open flag on the Verify card (design 09 section 11): what the reviewer flagged, what the agent made of it, and
// how to finish it here. A flagged block is reached only through "open in Verify" (it is never in the queue).
//
// On a short window (200 percent zoom, design 13 section 8.3) the notice folds to its summary line and a Details
// toggle, the same pattern as the review status block, so the page strip and the block text stay on screen.
import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAgentItems } from "../api/queries";
import type { AgentItemView, BlockDetail, Flag } from "../api/schema";
import Copy from "../onboarding/Copy";
import { usePublishedHeight } from "../shell/publishHeight";
import { FLAG_CATEGORIES, FLAG_RESOLUTION, FOCUS } from "../verify/labels";
import { stuck, triedText } from "./outcome";

const CATEGORY = new Map(FLAG_CATEGORIES.map((c) => [c.id, c.label]));
const LINK = "font-medium text-act-ink underline underline-offset-2 hover:text-act-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus";

export default function FlagNotice({ detail }: { detail: BlockDetail }) {
  const open = (detail.flags ?? []).filter((f) => f.status === "open");
  return open.length ? <OpenFlags open={open} /> : null;
}

/** "Agent: tried once", with the waiting proposal; the agent items are read only for a flagged block. */
function AgentWords({ it, loading, failed }: { it: AgentItemView | undefined; loading: boolean; failed: boolean }) {
  return (
    <span data-testid="verify-flag-agent">
      Agent: {it ? triedText(it) : loading ? "loading..." : failed ? "status unavailable" : "not tried yet"}
      {it?.pending_proposal_id ? ", a proposal is waiting on the Agent screen" : ""}
      {it && stuck(it) ? <span className="sr-only">. The agent could not fix it.</span> : null}
    </span>
  );
}

function OpenFlags({ open }: { open: Flag[] }) {
  const items = useAgentItems();
  const byFlag = new Map((items.data ?? []).map((i) => [i.flag.id, i]));
  const [details, setDetails] = useState(false);
  const detailsId = useId();
  const one = open.length === 1 ? open[0] : null;
  const ref = useRef<HTMLElement>(null);
  // the page strip gives this height back on a short window (design 13 section 8.3)
  usePublishedHeight(ref, "--flag-notice");
  const agent = (f: Flag) => <AgentWords it={byFlag.get(f.id)} loading={items.isLoading} failed={items.isError} />;
  return (
    <section
      ref={ref}
      role="region"
      aria-label="Open flag on this block"
      data-testid="verify-flag"
      className="shrink-0 space-y-1 border-b border-line bg-needs-wash px-4 py-2.5 text-sm text-ink short:py-0.5 wide:px-7"
    >
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 short:truncate" data-testid="verify-flag-summary">
          <span className="font-semibold">Flagged: {open.map((f) => CATEGORY.get(f.category) ?? f.category).join(", ")}</span>
          {one ? <> · {agent(one)}</> : null}
        </p>
        <button
          type="button"
          aria-expanded={details}
          aria-controls={detailsId}
          onClick={() => setDetails((d) => !d)}
          className={`hidden min-h-[1.5rem] shrink-0 rounded-lg border border-needs-line bg-raised px-2 text-xs font-medium text-ink hover:bg-sunk short:inline-block ${FOCUS}`}
        >
          {details ? "Fewer details" : "Details"}
        </button>
      </div>
      <div id={detailsId} className={`space-y-1 ${details ? "" : "short:hidden"}`}>
        {one ? (
          one.note ? (
            <p>
              <q className="text-muted">{one.note}</q>
            </p>
          ) : null
        ) : (
          open.map((f) => (
            <p key={f.id} className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-semibold">{CATEGORY.get(f.category) ?? f.category}</span>
              {f.note ? <q className="text-muted">{f.note}</q> : null}
              {agent(f)}
            </p>
          ))
        )}
        <p className="text-muted">
          {FLAG_RESOLUTION} <Copy text="Here: Approve ({vApprove}) or Edit ({vEdit}) after checking it against the page, or " />
          <Link to="/agent" className={LINK}>
            go to the Agent screen
          </Link>{" "}
          to run the agent pass again.
        </p>
      </div>
    </section>
  );
}
