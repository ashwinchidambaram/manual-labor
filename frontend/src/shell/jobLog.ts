// A job's log as sentences (design 09 section 11): the log rows are the worker's JSON events; the reviewer reads one
// plain line per event, never a JSON dump. Heartbeats are progress noise and are left out.
import { outcomeText } from "../agent/outcome";

type Row = Record<string, unknown>;

const NODE: Record<string, string> = {
  ingest: "Adding the file",
  parse: "Reading",
  figures: "Finding figures",
  score: "Scoring",
  group: "Grouping into topics",
  clean: "Cleaning up text",
  score2: "Scoring the cleaned text",
  agent: "Agent pass",
  assemble: "Assembling articles",
  export: "Building the export",
};

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : typeof v === "number" ? String(v) : null);
const node = (v: unknown): string => {
  const s = str(v);
  return s ? (NODE[s] ?? s.replace(/_/g, " ")) : "A step";
};
const on = (doc: unknown): string => (str(doc) ? ` (${str(doc)})` : "");
const status = (v: unknown): string => {
  const s = str(v);
  if (s === "done" || s === "ok") return "done";
  if (s === "error" || s === "failed") return "ended with an error";
  return s ?? "no status";
};

/** One sentence for one log row, or null for a row a reviewer does not need (heartbeats). */
export function jobLogLine(r: Row): string | null {
  const ev = str(r.event);
  switch (ev) {
    case "heartbeat":
      return null;
    case "job_start": {
      const n = Number(r.units ?? 0);
      return n > 0 ? `Started: ${n} step${n === 1 ? "" : "s"} to do.` : "Started.";
    }
    case "agent_outcome": {
      const round = Number(r.round ?? 1);
      return `Flag ${str(r.flag_id) ?? "?"}${round > 1 ? ` (try ${round})` : ""}: ${outcomeText(str(r.outcome) ?? "unknown", str(r.detail))}.`;
    }
    case "proposal": {
      const d = (r.draft ?? {}) as Row;
      return `Flag ${str(d.flag_id) ?? "?"}: a proposal is ready on the Agent screen.`;
    }
    case "unit_done":
      return `${node(r.node)}${on(r.doc)}: ${status(r.status)}.`;
    case "job_end": {
      if (str(r.status) === "done") return "Finished.";
      const err = str(r.error);
      return `Stopped: ${status(r.status)}${err ? `. ${err}` : ""}.`;
    }
    default:
      break;
  }
  if (str(r.message)) return str(r.message);
  if (str(r.stage)) {
    const d = str(r.detail);
    return `${node(r.stage)}${on(r.doc)}: ${status(r.status)}${d ? `. ${d}` : ""}.`;
  }
  const parts = Object.entries(r)
    .filter(([k, v]) => k !== "line" && v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`);
  return parts.length ? parts.join("; ") : null;
}

export const jobLogLines = (rows: Row[]): string[] => rows.map(jobLogLine).filter((l): l is string => l !== null);
