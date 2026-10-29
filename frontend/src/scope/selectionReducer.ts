// Pure optimistic reducer mirroring the server's selection ops (design 08 section 3.3).
import type { SelectionOp, Split, View } from "../api/schema";
import type { GroupsIndex } from "./derive";

export interface SelState {
  ids: ReadonlySet<string>;
  split: Split;
  view: View;
}

function add(ids: ReadonlySet<string>, more: Iterable<string>, idx: GroupsIndex): ReadonlySet<string> {
  const next = new Set(ids);
  for (const b of more) if (idx.selectable.has(b)) next.add(b);
  return next.size === ids.size ? ids : next;
}

function remove(ids: ReadonlySet<string>, less: Iterable<string>): ReadonlySet<string> {
  const next = new Set(ids);
  for (const b of less) next.delete(b);
  return next.size === ids.size ? ids : next;
}

/** Never mutates. `set_view` / `set_split` return the very same `ids` instance. */
export function reduce(state: SelState, op: SelectionOp, idx: GroupsIndex): SelState {
  switch (op.op) {
    case "select":
      return { ...state, ids: add(state.ids, op.block_ids ?? [], idx) };
    case "deselect":
      return { ...state, ids: remove(state.ids, op.block_ids ?? []) };
    case "select_group":
    case "deselect_group": {
      const src = op.group_id ? (op.subtree ? idx.subtree : idx.own).get(op.group_id) : undefined;
      if (!src || !src.length) return state;
      return { ...state, ids: op.op === "select_group" ? add(state.ids, src, idx) : remove(state.ids, src) };
    }
    case "set_view":
      return op.view ? { ...state, view: op.view } : state;
    case "set_split":
      return op.split ? { ...state, split: op.split } : state;
  }
}
