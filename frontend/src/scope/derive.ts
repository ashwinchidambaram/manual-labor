// Pure helpers for the Scope screen (design 08 section 3). No React, no I/O.
import type {
  DocGroups,
  Group,
  GroupCoverage,
  GroupsFile,
  ScopeBlocks,
  ScopeSummary,
  SelectionOut,
  Split,
  View,
} from "../api/schema";

const BLOCK_ID_RE = /^b-([a-z0-9]+(?:-[a-z0-9]+)*)-p(\d+)-(\d+)$/;

/** TS port of manuallabor.ids.BLOCK_ID_RE. Returns null for FIG- ids and malformed strings. */
export function parseBlockId(id: string): { slug: string; page: number; n: number } | null {
  const m = BLOCK_ID_RE.exec(id);
  return m ? { slug: m[1], page: Number(m[2]), n: Number(m[3]) } : null;
}

export function lowCohesion(g: Group, params: { low_cohesion: number }): boolean {
  return !g.is_unassigned && g.cohesion != null && g.cohesion < params.low_cohesion;
}

/** "none" / "all" / "62%" / "n/a" (design 3.1). */
export function coverageLabel(fraction: number | null): string {
  if (fraction == null) return "n/a";
  if (fraction <= 0) return "none";
  if (fraction >= 1) return "all";
  return `${Math.round(fraction * 100)}%`;
}

export type CheckState = "checked" | "mixed" | "unchecked";

export function checkState(selected: number, total: number): CheckState {
  if (total <= 0 || selected <= 0) return "unchecked";
  return selected >= total ? "checked" : "mixed";
}

/** Smart toggle: fully selected -> deselect, otherwise (unchecked or partial) select the rest. */
export function smartToggle(state: CheckState): "select_group" | "deselect_group" {
  return state === "checked" ? "deselect_group" : "select_group";
}

// ---- tree ----------------------------------------------------------------------------------

export interface TreeNode {
  group: Group;
  children: TreeNode[];
  parent: TreeNode | null;
}

function isAncestor(candidate: TreeNode, of: TreeNode): boolean {
  for (let n: TreeNode | null = of; n; n = n.parent) if (n === candidate) return true;
  return false;
}

/** parent_id -> nested model, in GroupsFile order. Unknown parents become roots. */
export function buildTree(groups: readonly Group[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  for (const g of groups) byId.set(g.id, { group: g, children: [], parent: null });
  const roots: TreeNode[] = [];
  for (const g of groups) {
    const node = byId.get(g.id)!;
    const parent = g.parent_id && g.parent_id !== g.id ? byId.get(g.parent_id) : undefined;
    if (parent && !isAncestor(node, parent)) {
      node.parent = parent;
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

export interface Row {
  group: Group;
  docId: string;
  depth: number; // 1-based aria-level
  hasChildren: boolean;
  childCount: number;
  parentId: string | null;
  posInSet: number;
  setSize: number;
}

/** Group ids that start expanded: top-level nodes that have children (design 4.2: "depth 1"). */
export function defaultExpanded(docs: readonly DocGroups[]): Set<string> {
  const out = new Set<string>();
  for (const d of docs)
    for (const root of buildTree(d.groups.structure)) if (root.children.length) out.add(root.group.id);
  return out;
}

/** Visible rows of one view, across docs, in reading order. Doc headings are not rows. */
export function visibleRows(docs: readonly DocGroups[], view: View, expanded: ReadonlySet<string>): Row[] {
  const rows: Row[] = [];
  for (const d of docs) {
    if (view === "topic") {
      const topics = [...d.groups.topics].sort((a, b) => Number(b.is_unassigned) - Number(a.is_unassigned));
      topics.forEach((g, i) =>
        rows.push({
          group: g,
          docId: d.doc_id,
          depth: 1,
          hasChildren: false,
          childCount: 0,
          parentId: null,
          posInSet: i + 1,
          setSize: topics.length,
        }),
      );
      continue;
    }
    const walk = (nodes: TreeNode[], depth: number): void => {
      nodes.forEach((n, i) => {
        rows.push({
          group: n.group,
          docId: d.doc_id,
          depth,
          hasChildren: n.children.length > 0,
          childCount: n.children.length,
          parentId: n.parent?.group.id ?? null,
          posInSet: i + 1,
          setSize: nodes.length,
        });
        if (n.children.length && expanded.has(n.group.id)) walk(n.children, depth + 1);
      });
    };
    walk(buildTree(d.groups.structure), 1);
  }
  return rows;
}

// ---- cursor navigation -----------------------------------------------------------------------

export function moveCursor(rows: readonly Row[], current: string | null, delta: 1 | -1): string | null {
  if (!rows.length) return null;
  const i = rows.findIndex((r) => r.group.id === current);
  if (i < 0) return rows[0].group.id;
  return rows[Math.min(rows.length - 1, Math.max(0, i + delta))].group.id;
}

/** `ArrowRight`: closed node -> expand; open node -> first child. */
export function expandAction(
  rows: readonly Row[],
  current: string,
  expanded: ReadonlySet<string>,
): { expand: string } | { move: string } | null {
  const i = rows.findIndex((r) => r.group.id === current);
  if (i < 0 || !rows[i].hasChildren) return null;
  if (!expanded.has(current)) return { expand: current };
  const next = rows[i + 1];
  return next && next.parentId === current ? { move: next.group.id } : null;
}

/** `ArrowLeft`: open node -> collapse; otherwise (leaf or closed) -> parent. */
export function collapseAction(
  rows: readonly Row[],
  current: string,
  expanded: ReadonlySet<string>,
): { collapse: string } | { move: string } | null {
  const r = rows.find((x) => x.group.id === current);
  if (!r) return null;
  if (r.hasChildren && expanded.has(current)) return { collapse: current };
  return r.parentId ? { move: r.parentId } : null;
}

// ---- selection / summary -----------------------------------------------------------------------

export interface GroupsIndex {
  /** every selectable block id (union of structure block ids, as on the server) */
  selectable: Set<string>;
  own: Map<string, string[]>;
  subtree: Map<string, string[]>;
  /** group id -> doc id */
  docOf: Map<string, string>;
}

export function buildGroupsIndex(docs: readonly DocGroups[]): GroupsIndex {
  const idx: GroupsIndex = { selectable: new Set(), own: new Map(), subtree: new Map(), docOf: new Map() };
  for (const d of docs) {
    for (const g of [...d.groups.structure, ...d.groups.topics]) {
      idx.own.set(g.id, g.block_ids);
      idx.docOf.set(g.id, d.doc_id);
    }
    for (const g of d.groups.structure) for (const b of g.block_ids) idx.selectable.add(b);
    const collect = (n: TreeNode): string[] => {
      const ids = [...n.group.block_ids];
      for (const c of n.children) ids.push(...collect(c));
      idx.subtree.set(n.group.id, ids);
      return ids;
    };
    for (const root of buildTree(d.groups.structure)) collect(root);
    for (const t of d.groups.topics) idx.subtree.set(t.id, t.block_ids);
  }
  return idx;
}

export function coverageIndex(sel: SelectionOut | undefined): Map<string, GroupCoverage> {
  const m = new Map<string, GroupCoverage>();
  for (const rep of sel?.coverage ?? []) for (const c of [...rep.structure, ...rep.topics]) m.set(c.group_id, c);
  return m;
}

/**
 * Own-view selected/total used by the checkbox, counted locally from the selection so the box
 * flips in the same frame as the click. Structure rows count their subtree. (Coverage chips of
 * the other view stay server-computed.)
 */
export function rowCounts(
  ids: ReadonlySet<string>,
  idx: GroupsIndex,
  groupId: string,
  view: View,
): { selected: number; total: number } {
  const list = (view === "structure" ? idx.subtree : idx.own).get(groupId);
  if (!list) return { selected: 0, total: 0 };
  let selected = 0;
  for (const b of list) if (ids.has(b)) selected++;
  return { selected, total: list.length };
}

export function rowFraction(c: GroupCoverage | undefined, view: View): number | null {
  if (!c) return null;
  return view === "structure" ? c.subtree_fraction : c.fraction;
}

export interface BlockMeta {
  doc: string;
  figure: boolean;
  queued: boolean;
  numeric: boolean;
}

export function buildBlockIndex(rows: readonly ScopeBlocks[]): Map<string, BlockMeta> {
  const m = new Map<string, BlockMeta>();
  for (const d of rows)
    for (const b of d.blocks)
      m.set(b.id, { doc: d.doc_id, figure: b.type === "figure", queued: b.status === "queued", numeric: b.numeric });
  return m;
}

/** Mirrors manuallabor.grouping.selection.scope_summary (design 3.2). `docs`, `pages` and the
 * article counts follow the selected ids and the groups, like `blocks`; only `figures` and the
 * review load read the block index, so a grouped document whose scores are pending (absent from
 * the index) still counts as in scope. */
export function summaryFrom(
  ids: ReadonlySet<string>,
  blockIndex: ReadonlyMap<string, BlockMeta>,
  docs: readonly { doc_id: string; groups: GroupsFile }[],
  threshold: number,
  split: Split,
): ScopeSummary {
  let docCount = 0;
  let perTopic = 0;
  let figures = 0;
  let queued = 0;
  let numeric = 0;
  const pages = new Set<string>();
  const byDoc = new Map<string, string[]>();
  for (const id of ids) {
    const p = parseBlockId(id);
    if (!p) continue;
    const list = byDoc.get(p.slug);
    if (list) list.push(id);
    else byDoc.set(p.slug, [id]);
  }
  for (const d of docs) {
    const mine = byDoc.get(d.doc_id);
    if (!mine) continue;
    for (const id of mine) {
      pages.add(`${d.doc_id}:${parseBlockId(id)!.page}`);
      const m = blockIndex.get(id);
      if (!m) continue;
      if (m.figure) figures++;
      if (m.queued) {
        queued++;
        if (m.numeric) numeric++;
      }
    }
    docCount++;
    perTopic += d.groups.topics.filter((t) => t.block_ids.some((b) => ids.has(b))).length;
  }
  return {
    docs: docCount,
    articles_per_topic: perTopic,
    articles_per_document: docCount,
    articles: split === "per_topic" ? perTopic : docCount,
    blocks: ids.size,
    figures,
    pages: pages.size,
    review_load: { queued, numeric_queued: numeric, threshold },
  };
}
