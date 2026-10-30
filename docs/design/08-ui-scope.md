# Module 8 design: UI, Scope screen

Inputs: SPEC §7, §7.1, §7.2, §9, §10; CLAUDE.md (module 8 gate: *toggle preserves selection; counts live; keyboard-navigable*); findings (M4: subtree select; M7: selection in SQLite, threshold is a view filter, jobs); 04-grouping §4 to §5; 07-api-state §5 to §7. Implemented routes read from `manuallabor/api/routers/{project,sources,scope,jobs}.py`.

## 0. Decisions (open issues resolved)

| # | Question | Choice | Why |
|---|---|---|---|
| D1 | Router | `react-router-dom@6` with `createBrowserRouter` | `labor serve` already falls back to `index.html` for any non-`/api` GET and Vite dev does the same, so path routes work; deep links `/scope` survive reload. A hash router would make Playwright URLs ugly for no gain. |
| D2 | Data layer | `@tanstack/react-query@5` over the existing `openapi-fetch` client | "No global state library" is about client state. All Scope state except the view toggle and cursor is server state; Query gives caching, `refetchInterval` polling, optimistic `onMutate`/rollback and request dedupe, which would otherwise be a hand-rolled store. It is a cache, not a store: no `Provider` state of ours. One `QueryClient`, no persistence. |
| D3 | Selection ownership | Server (SQLite). Client keeps an optimistic overlay inside the Query cache (`setQueryData`), never a second copy | Reload restores from `GET /api/scope/selection`. |
| D4 | View toggle | Client state in the URL query `?view=structure\|topic`, mirrored to the server via `set_view` (so `Selection.active_view` is persisted and reload restores it) | Selection `block_ids` is byte-identical across the toggle (04 §5). |
| D5 | e2e seeding | `frontend/e2e/global-setup.ts` builds a **cached** mock project once from `tests/fixtures/project-a` (`clean.pdf`, `figures.pdf`), then copies it per Playwright run | See §6. Committed pre-built project rejected: it drifts when `ALGO_VERSION`s change and bloats the repo. Running parse per test run rejected: Docling is slow. |
| D6 | Styling | Tailwind utility classes only; no component library, no CSS files beyond `index.css` base | Minimal. Visual polish is out of scope; semantics, focus rings, contrast are in scope. |
| D7 | Virtualisation | None for v1. Rows are groups (tens to low hundreds), not blocks | See §3.4. Revisit only if a project has > 500 groups. |
| D8 | Live counts | Client derives `blocks`, `pages` exactly; `figures`, `queued` via a compact per-block index (gap G1); reconciled with the server `summary` from every PUT response | See §3.2. |

New frontend dependencies (pinned in `package.json`): `react-router-dom@6.x`, `@tanstack/react-query@5.x`, dev: `msw@2.x`, `@testing-library/user-event@14`.

## 1. App shell

### 1.1 Routes and layout

| Path | Screen | Module |
|---|---|---|
| `/` | redirect to `/scope` | 8 |
| `/scope` | Scope | 8 |
| `/verify`, `/agent`, `/export` | `<ComingSoon name>` stub: heading + "Back to Scope" link. Real screens land in modules 9 to 11 | 8 (stubs) |
| `*` | NotFound with link to `/scope` | 8 |

`AppShell` (`src/shell/AppShell.tsx`): header (project name from `GET /api/project`, a mock badge if `mock`, step nav Scope / Verify / Agent / Export as `<nav aria-label="Screens">` links, `JobsBar`), then a 3-column CSS grid below: left rail 18rem (`SourcesList`), main (`<Outlet/>`), right rail 20rem (`ModelPanel`, Scope route only; other routes get a full-width main). Below 1024 px the rails stack under the main pane. The rails and header belong to the Scope route element, not the shell, except `JobsBar` and the nav.

```
src/
  main.tsx                 QueryClientProvider + RouterProvider
  router.tsx               route table
  hotkeys.ts               the single key map (§4)
  shell/{AppShell,JobsBar,ErrorBoundary,Help}.tsx
  hooks/{useHotkeys,useRovingTree,useJobsPolling}.ts
  api/{client.ts,types.ts,queries.ts}      queries.ts = all useQuery/useMutation wrappers, one place
  scope/
    ScopeScreen.tsx, SourcesList.tsx, ViewToggle.tsx, GroupTree.tsx, GroupRow.tsx,
    SelectionSummary.tsx, SplitModeControl.tsx, ModelPanel.tsx, ConfirmButton.tsx
    derive.ts              pure helpers (§3)
    selectionReducer.ts    pure optimistic reducer (§3.3)
```

Components stay under ~150 lines; every file in `scope/` except `ScopeScreen` is presentational plus one hook call.

### 1.2 Data layer and polling

All calls go through `client` (`openapi-fetch`) typed from `src/api/types.ts`; contract-only types from `src/types/generated.ts`. Errors: a response middleware turns non-2xx into `ApiError{status, code, detail}` (body is `{detail, code}`); thrown from the query fn so Query's `error` is typed.

| Query key | Endpoint | `staleTime` | Notes |
|---|---|---|---|
| `['project']` | GET `/api/project` | Infinity | name, `mock`, `config.article_split`, `config.threshold` |
| `['sources']` | GET `/api/sources` | 0, refetch on job finish | |
| `['status']` | GET `/api/status` | 0 | `unregistered_sources`, `jobs_running` |
| `['groups']` | GET `/api/scope/groups` | Infinity; invalidated when a job of kind run/ingest finishes | `list[DocGroups]`: `GroupsFile` + `CoverageReport` per doc |
| `['selection']` | GET `/api/scope/selection` | Infinity; written by mutations | `SelectionOut{selection, coverage[], summary}` |
| `['summary']` | GET `/api/scope/summary` | 0 | used only to reconcile after a job finishes (threshold or re-score changes `queued`) |
| `['models']` | GET `/api/scope/models` | 30 s | `{models, probe, suggestions}`; 404 `no_probe` is not an error here: `probe=None` |
| `['jobs','active']` | GET `/api/jobs?status=queued&status=running` | 0 | polling, see below |
| `['block-index']` | GET `/api/scope/blocks` (gap G1) | Infinity; invalidated with `groups` | |

**Polling rule (`useJobsPolling`)**: the `['jobs','active']` query has `refetchInterval: (q) => q.state.data?.length ? 1000 : false`, so it polls every second while any job is queued/running and stops when idle. It also refetches on window focus and after any mutation that returns a `JobInfo` (ingest, confirm, regroup, apply-tier) by `setQueryData` + `invalidate`. When the active list shrinks, the hook compares to the previous list; for each job that disappeared it GETs `/api/jobs/{id}`, and on `done` invalidates `sources`, `status`, `groups`, `selection`, `summary`, `block-index`, `models`; on `failed|interrupted|cancelled` shows the error in `JobsBar` (job `error`, `message`) with a Dismiss button and does not invalidate. No timers outside Query. Playwright and unit tests control time via MSW responses, not fake timers.

**Loading / error / empty states** (each has a stable `data-testid`):

| State | Where | Rendering |
|---|---|---|
| `loading` | any panel's first fetch | skeleton rows, `aria-busy="true"` on the region |
| `error` | any panel | inline `role="alert"` card with `code`, `detail` and a Retry button (`r` when the panel is focused is not bound; click only); other panels keep working |
| 503 / network down | shell | a top banner "Server not reachable", polling continues every 3 s |
| no docs | Scope | empty-state card with the ingest button and drop zone (`testid=scope-empty`) |
| docs not yet grouped (`groups.length < sources.length`, or job running) | tree | rows for grouped docs; a per-doc "grouping..." placeholder for the rest; the tree is usable while later docs are still processing (CLAUDE.md: never block the UI) |
| `topic_status == "failed"` | topic view | notice "Topics unavailable: {topic_error}. Structure view still works."; toggle stays enabled and the topic list shows only Unassigned |

### 1.3 Focus management (global)

Single focus zone model: `data-zone` in {`sources`, `tree`, `summary`, `models`}. `Tab`/`Shift+Tab` move between zones in DOM order (rails and main are each one tab stop; arrows move inside). `Esc` returns focus to the tree from anywhere. On first load focus goes to the tree (`autoFocus` on the roving item once groups load). Mutations never steal focus. After a view toggle the cursor stays on the same *index-equivalent* row if the group exists in the new view, else the first row, and focus stays in the tree. Every interactive element has a visible `focus-visible:ring-2` ring.

## 2. Scope components

| Component | Props / data | Renders | Behaviour |
|---|---|---|---|
| `SourcesList` | `useSources`, `useStatus` | one row per `SourceInfo`: filename, `kind` badge, `pages`, parse status chip derived from `nodes` (all `fresh` = "Ready"; any `failed` = "Failed: {node}"; any `stale|missing` or an active job on `doc` = "Processing {node}"; `unregistered_sources` shown as "Not ingested") ; `ocr_warning` as an amber `role="note"` line with warning icon text "OCR: ..." and the page count; for `kind == scanned_pdf` always shows "Scanned: OCR text" | "Add documents" button (file input, multiple, `.pdf,.docx`) POSTs multipart to `/api/sources` -> `JobInfo` into `JobsBar`. "Re-run" button (only when a doc has stale/failed nodes) POSTs `/api/jobs {to:"group"}`. Rows are `button`s that scroll the tree to that doc's first group. No delete in v1. |
| `ViewToggle` | `view`, `onChange` | `role="radiogroup"` with two `role="radio"`: "Suggested topics" / "Document structure" | `t` toggles. Calls `setView` (URL + `set_view` PUT). |
| `GroupTree` | `DocGroups[]`, `Selection`, `view` | `role="tree"` (structure) or `role="listbox" aria-multiselectable` (topics); see §4 for ARIA | One doc heading row (`role="group"` label = filename) then its groups. Reading-order = `GroupsFile` order. |
| `GroupRow` | `Group`, `GroupCoverage` (own view), `GroupCoverage` (other view) | checkbox state (checked / indeterminate / unchecked) from own-view `selected`/`total` (structure rows: `subtree_selected/subtree_total`); title (structure: `section_number` + title, indented by `level`); meta line `pp. 3-7, 12`, `{block_count} blocks`, `{figure_count} figures`, `{n} sections` (topic: `section_ids.length`; structure: number of children); cohesion `0.42` (topic only); low-cohesion marker; coverage chip | click or Space toggles the row. Rows are memoised on `(group.id, selected, view)`. |
| `SelectionSummary` | `ScopeSummary` (live) | "What you will get": articles (per active split), docs, blocks, figures, pages; "Estimated review: {queued} blocks ({numeric_queued} with numeric specs) under threshold {threshold}", label includes the word "estimated" (04 §5) | `aria-live="polite"` on the numbers; `data-testid` per number (`sum-articles`, `sum-blocks`, `sum-figures`, `sum-pages`, `sum-queued`). |
| `SplitModeControl` | `Selection.article_split`, `summary` | radiogroup "One article per topic" / "One article per document" with the resulting count in each label | `s` cycles. PUT `set_split`. In `per_topic` the article count comes from the topic view whatever the active view (04 §5); a hint line says so when the structure view is active. |
| `ModelPanel` | `['models']` | table task -> `provider/model` for `cleanup, grouping, vision, verifier, embeddings` (rows for `metadata`/`agent` only if set); hardware line from `probe` (RAM, GPU/VRAM, effective model memory, Ollama reachable/missing models); suggestion: `default_tier` (+ `default_reason`), a tier selector showing for each task the tier's model, `fits`, `speed_class`, `present`; `pull_commands[tier]` in a copyable `<pre>` with a Copy button (never executed, SPEC §8) ; "Apply {tier}" button -> POST `/api/config/apply-tier {tier}`; result `stale[]` shown as "N stages will re-run"; if 422 shows `detail`; when no probe: "Run hardware probe" -> POST `/api/probe` | `m` focuses the panel. Applying never auto-pulls. The applied tier replaces `['models']` from the response `models`. |
| `JobsBar` | `['jobs','active']` | per running job: kind, `node`, `doc`, `message`, `<progress value={progress}>` plus `units_done/units_total`; Cancel button (POST `/api/jobs/{id}/cancel`); failed job banner | polling per §1.2. Hidden when idle. |
| `ConfirmButton` | `summary.blocks` | "Confirm scope and go to Verify" (disabled with reason when `blocks == 0` or topics/groups still processing) | `g` or Enter on it: POST `/api/scope/confirm {}` -> `JobInfo` (run `to=score2`), then navigate to `/verify` immediately (Verify shows the job in `JobsBar` and is usable as blocks score, SPEC §9). |

Marker rules: `lowCohesion(g, params) = !g.is_unassigned && g.cohesion != null && g.cohesion < params.low_cohesion` (`params` from that doc's `GroupsFile`; the 0.30 constant is never hard-coded). Marker = amber badge text "Low cohesion" + `aria-label="Low cohesion {value}"` + `data-testid="low-cohesion"` (never colour only). Unassigned row: title "Unassigned blocks", pinned first in the topic list (t000 first, 04 §4), badge "Catch-all", no cohesion, selectable like any topic. Header/footer blocks are not selectable and appear nowhere in the tree; `dropped` in a `SelectionOut` is ignored by the UI (it only matters for CLI/API clients).

## 3. Data flow, counts, performance

### 3.1 Which endpoint feeds which component

| Component | Reads | Writes |
|---|---|---|
| `SourcesList` | `sources`, `status` | POST `/api/sources`, POST `/api/jobs` |
| `GroupTree`/`GroupRow` | `groups` (structure and topics, own-view `selected/total`), `selection` (`selection.block_ids`, `coverage[]` for the other view's fraction) | PUT `/api/scope/selection` |
| `SelectionSummary`, `SplitModeControl` | derived summary (§3.2) | PUT `selection` (`set_split`) |
| `ViewToggle` | `selection.active_view` | PUT `set_view` |
| `ModelPanel` | `models` | POST `/api/probe`, POST `/api/config/apply-tier` |
| `JobsBar` | `jobs/active` | POST `/api/jobs/{id}/cancel` |
| `ConfirmButton` | `summary`, `jobs/active` | POST `/api/scope/confirm` |

Coverage is computed only on the server (`coverage()` in grouping, 04 §4). The client never recomputes coverage; it renders `GroupCoverage.fraction` (structure rows use `subtree_fraction`) from `SelectionOut.coverage[doc].{structure|topics}` for the *other* view and `selected/total` for the own view. A row in the other view reads e.g. "62% in selection" (`Math.round(fraction*100)`, `none` when 0, `all` when 1, `n/a` when `fraction == null`). Group id -> coverage lookup is a `Map` built once per `selection` payload.

### 3.2 Live counts

Two-phase update on every selection change, so counts feel instant but are never wrong for long:

1. **Optimistic (sync, same frame)**: `selectionReducer(selection, op, groupsIndex)` computes the next `block_ids` Set locally (it mirrors the server ops: `select`/`deselect`; `select_group`/`deselect_group` with `subtree` = union of the row's and its descendants' `block_ids` from a pre-built `subtreeBlocks: Map<groupId, string[]>`; `set_view`/`set_split` touch no ids). `derive.summaryFrom(selectionSet, blockIndex, groupsByDoc, split, threshold)` returns a `ScopeSummary`: `blocks = |S|`; `pages` = distinct `(doc, page)` parsed from block ids with `parseBlockId` (a TS port of `ids.BLOCK_ID_RE`; page group of `^b-(slug)-p(\d+)-(\d+)$`); `figures`/`queued`/`numeric_queued` from `blockIndex` (gap G1); `docs`, `articles_per_topic` (topic groups with >= 1 selected block, incl. Unassigned), `articles_per_document = docs`. The cache entries `selection` and `summary` are updated with `setQueryData` and the coverage chips of the *other* view are marked `data-stale="true"` (dimmed) until step 2 (coverage is server-only).
2. **Reconcile**: a debounced (150 ms trailing, coalescing consecutive ops into one) PUT sends the ops. Ops are sent individually in order (each carries its own `request_id` = `crypto.randomUUID()`, making retries idempotent); the debounce only delays the first send and serialises the rest through one in-flight promise queue so server order == UI order. The final response `SelectionOut` replaces `selection`/`summary` in the cache (server wins). If its `summary` differs from the optimistic one, a `console.warn` in dev and a Vitest invariant catches the drift (tests assert equality, §5 U6). PUT failure: rollback to the last server `SelectionOut`, show a toast "Selection not saved: {detail}", and refetch.

If G1 is not provided, fallback: `figures` and `queued` are shown from the last server summary with a "updating" spinner until the PUT returns (typically < 100 ms on localhost); the gate (counts live) is then verified in e2e on the server numbers. G1 is recommended because it makes unit tests pure.

### 3.3 `selectionReducer` (pure, `scope/selectionReducer.ts`)

`reduce(state: {ids: ReadonlySet<string>, split, view}, op: SelectionOp, idx: GroupsIndex): state`. Contract: returns a new state; never mutates; `set_view` leaves `ids` the same Set instance (so the toggle-preserves-selection property is checked with `===`); ids outside `idx.selectable` are dropped; `select_group` on a group with 0 blocks is a no-op. Row toggle semantic ("smart toggle"): if the row's own-view `selected == total` and `total > 0` -> `deselect_group`, else `select_group` (indeterminate -> select the rest). Structure rows always send `subtree: true`; topic rows `subtree: false` (findings M4).

### 3.4 Performance limits (SPEC §9: 1,000+ blocks)

| Item | Size | Cost | Decision |
|---|---|---|---|
| Groups per project | typical 20 to 300; hard design cap = n/4 topics + one structure group per heading | O(groups) DOM nodes | Render all; memoised rows; no virtualisation in v1 |
| `block_ids` in selection | 1,000 to 20,000 strings | Set build < 5 ms | Keep as `Set<string>` in a `useMemo` keyed on the `selection` object |
| PUT payload for `select_group` | one `group_id` (never an id list) | tiny | Group ops send ids only for `select`/`deselect` |
| "Select all" / "clear" | uses the two existing ops with group ids of every top-level topic (`select_group` per doc via one op each, batched sequentially) | one request per doc | No bulk op needed; optional G2 |
| Block index (G1) | ~60 bytes/block | 60 KB at 1,000 blocks | Fetched once per grouping version |
| Re-render on toggle | one row + summary + the other view's chips | O(changed rows) | rows are `React.memo`; coverage map lookups by id |

Stated limit: up to 500 group rows and 20,000 blocks stay under 16 ms per interaction in jsdom-free profiling (manual check once, recorded in PROGRESS.md). If a project exceeds 500 group rows, `GroupTree` switches to windowing (`@tanstack/react-virtual`) behind a `rows > 500` guard; not implemented in v1, tracked as an open item.

## 4. Keyboard and accessibility (the gate)

### 4.1 `hotkeys.ts` (single map)

```
HOTKEYS: Record<HotkeyId, { keys: string[]; scope: 'global'|'scope'|'tree'|'models'; label: string; when?: string }>
```

Matching rules in `useHotkeys`: ignore events from `input, textarea, select, [contenteditable]`; ignore with Ctrl/Meta/Alt; `Shift` significant only for `?`; key compared via `event.key` lower-cased; `scope` entries active only on `/scope`; `tree` entries only when focus is inside `[data-zone="tree"]`. A unit test (U1) asserts no two entries share a key within overlapping scopes, every entry has a `label`, and Help renders from the same map.

| Id | Key(s) | Scope | Action |
|---|---|---|---|
| `help` | `?` | global | toggle Help dialog (`role="dialog"`, focus trapped, `Esc` closes) |
| `goScope` | `1` | global | `/scope` |
| `goVerify` | `2` | global | `/verify` (stub in module 8) |
| `goAgent` | `3` | global | `/agent` |
| `goExport` | `4` | global | `/export` |
| `toggleView` | `t` | scope | switch view |
| `focusTree` | `Escape` | scope | focus the tree (closes Help first if open) |
| `focusSources` | `o` | scope | focus first source row |
| `focusModels` | `m` | scope | focus model panel; `m` again returns to the tree |
| `focusSummary` | `u` | scope | focus summary region |
| `splitMode` | `s` | scope | cycle article split per_topic <-> per_document |
| `selectAll` | `a` | scope | select every selectable block (all docs) |
| `selectNone` | `n` | scope | clear selection (confirm-less; reversible by `a`) |
| `confirm` | `g` | scope | confirm scope and go to Verify (disabled when 0 blocks: announces "Nothing selected" in the live region) |
| `moveDown` / `moveUp` | `j`, `ArrowDown` / `k`, `ArrowUp` | tree | move the roving cursor |
| `first` / `last` | `Home` / `End` | tree | |
| `expand` / `collapse` | `ArrowRight`, `l` / `ArrowLeft`, `h` | tree (structure) | expand closed node, else move to first child / collapse open node, else move to parent |
| `toggleRow` | `Space` | tree | smart-toggle the row (§3.3) |
| `selectOnly` | `Enter` | tree | clear selection, then select this row (own subtree for structure) |
| `selectWholeDoc` | `Shift+A` | tree | select the doc heading's every block (convenience) |

Space is not bound globally; `Enter` on a button elements does what the button says. `g` is the "go to Verify" the gate requires; the visible button is the same action.

### 4.2 Focus order and ARIA

Tab order: header nav -> `SourcesList` (one stop, arrows inside) -> view toggle (radiogroup, arrows inside) -> tree (one stop, roving `tabindex`) -> split control (radiogroup) -> summary -> confirm button -> model panel (tier radiogroup, Apply, Copy). The view toggle and split control keep native radio arrow behaviour.

| Element | Role and attributes |
|---|---|
| Structure tree | `role="tree"`, `aria-label="Document structure"`, `aria-multiselectable="true"`; node `role="treeitem"`, `aria-level`, `aria-setsize`, `aria-posinset`, `aria-expanded` (parents only), `aria-selected` (= fully selected), `aria-checked="mixed"` on partial via the visible checkbox `role="checkbox"` child; children in `role="group"`. Roving `tabindex=0` on the cursor item, `-1` elsewhere; `aria-activedescendant` is not used. |
| Topic list | `role="listbox"`, `aria-label="Suggested topics"`, `aria-multiselectable="true"`; rows `role="option"`, `aria-selected`; same roving cursor. |
| Doc heading | `role="presentation"` row inside the tree, skipped by the cursor (the cursor moves over groups only). |
| Coverage chip | text, e.g. `62% selected` with `aria-label="62 percent of this section is in your selection"`. |
| Live region | `<div role="status" aria-live="polite" data-testid="live">` announces "Selected: 128 blocks, 5 articles" after reconcile and "Switched to Document structure view" on toggle. |
| Expansion | Structure tree starts expanded to depth 1; expansion state is client-only, kept per group id in a `Set`, preserved across toggle (back to the tree it comes). |

Hotkeys never fire inside the file input, the Help dialog's inputs, or while `aria-busy`. Mouse users get the same operations: clicking a row toggles it; clicking the chevron expands.

## 5. Test plan

Tooling: Vitest + jsdom (existing), `@testing-library/react`, `user-event`, MSW (`msw/node`) with handlers in `src/test/handlers.ts` built from typed factory functions `makeGroupsFile()`, `makeSelectionOut()` (kept small: 2 docs, 3 sections with nesting, 3 topics + Unassigned, one low cohesion). All commands from `frontend/`.

### 5.1 Unit (pure, `src/scope/*.test.ts`, `src/hotkeys.test.ts`)

| # | Test |
|---|---|
| U1 | `HOTKEYS`: no key collisions among overlapping scopes; every entry has a label; ids match the type union |
| U2 | `parseBlockId` agrees with the Python regex on valid ids, rejects `FIG-` and malformed |
| U3 | `selectionReducer`: select, deselect, idempotence, ids sorted/deduped, unknown ids dropped |
| U4 | `select_group subtree=true` selects the group and all descendants; `deselect_group` inverse; leaf equals own blocks; topic rows never subtree |
| U5 | `set_view` returns the same Set instance (`===`) and unchanged `block_ids`; `set_split` likewise |
| U6 | `summaryFrom` equals the server `ScopeSummary` on a recorded fixture for 5 selections (empty, one topic, one subtree, all, mixed) incl. `articles_per_topic` counting Unassigned and `pages` distinct across docs |
| U7 | `smartToggle` row state: unchecked -> select, partial -> select, full -> deselect |
| U8 | `lowCohesion`: boundary at `params.low_cohesion` (strict `<`), `null`, and Unassigned are never low |
| U9 | `coverageLabel`: 0 -> "none", 1 -> "all", 0.617 -> "62%", null -> "n/a" |
| U10 | tree builder: `parent_id` -> nested model in `GroupsFile` order; roots with no parent; cycle-free; `level` consistent |
| U11 | cursor navigation helpers: next/prev over visible rows respect collapsed nodes; `collapse` on a leaf moves to parent |

### 5.2 Component (`*.test.tsx`, MSW)

| # | Test |
|---|---|
| C1 | `SourcesList`: ready / processing / failed chips from `nodes`; OCR warning text shown only when `ocr_warning`; scanned badge; upload posts multipart and shows a job |
| C2 | `ViewToggle`: radio semantics, `t` toggles, calls `set_view`, URL gets `?view=` |
| C3 | `GroupTree` structure: roles/aria-levels/expanded, indent by level, checkbox mixed state, subtree select sends `{op:"select_group", subtree:true}` |
| C4 | `GroupTree` topics: Unassigned first with "Catch-all", low-cohesion badge only on `cohesion < params.low_cohesion`, meta line (pages, counts, sections) |
| C5 | Coverage chips: in topic view each topic row shows structure-derived `fraction` of the *other* view; in structure view rows show `subtree_fraction`; dimmed while a PUT is in flight |
| C6 | `SelectionSummary`: renders all numbers, "estimated" wording, aria-live; zero state; changes when the mocked PUT returns |
| C7 | `SplitModeControl`: counts in labels, `s` cycles, structure-view hint present |
| C8 | `ModelPanel`: task table from `config.models`; probe + suggestion rows; pull commands for the selected tier; Apply posts `{tier}` and shows `stale` count; 422 shows `detail`; no-probe state offers probe |
| C9 | `JobsBar`: polls while a job is running (MSW returns running x2 then empty -> stops polling, asserted by request count), progress bar value, failed banner, cancel posts |
| C10 | Optimistic flow: toggling a row updates the summary before the PUT resolves; a rejected PUT rolls back and toasts; two quick toggles produce two ordered PUTs with distinct `request_id`s |
| C11 | Keyboard: roving tabindex, `j/k/Home/End`, `l/h` expand/collapse, `Space`, `Enter`, `t`, `s`, `a`, `n`, `m`, `?` open/close with focus trap, hotkeys ignored in inputs |
| C12 | States: loading skeleton + `aria-busy`, error alert with Retry, empty project, topic-failed notice, ungrouped doc placeholder |
| C13 | `ConfirmButton`: disabled at 0 blocks with reason; confirm posts and navigates to `/verify` |
| C14 | `ErrorBoundary` renders fallback, and the nav still works |

### 5.3 Playwright (`frontend/e2e/scope.spec.ts`), gate tests

Run against `labor serve <tmp-project> --dev --mock --port 8765` and Vite on 5173 (config in §6). `beforeEach` resets selection through the API (`PUT /api/scope/selection` with `deselect` of all, then `select` of all topic groups) so tests are independent. Helper `selected()` reads `[data-testid=sum-blocks]`; `rowByTitle(name)`.

| # | Test (maps to the gate) |
|---|---|
| E1 | **Toggle preserves selection + coverage %**: in topic view select topic A; switch to structure view with the toggle button; assert the summary numbers are unchanged; at least one structure row shows a coverage chip > 0% and < 100% or == 100% matching `GET /api/scope/selection` `coverage[].structure[].subtree_fraction` (read in the test via `request`); switch back, assert topic A is still checked |
| E2 | **Counts update live**: selection summary `sum-blocks` and `sum-pages` change within 100 ms of ticking a topic (before the network response: delay the PUT with `page.route` by 800 ms and assert the optimistic value first, then the reconciled server value equals `GET /api/scope/summary`) |
| E3 | **Keyboard-only flow** (no `mouse`/`click` calls; only `keyboard.press`): deselect all (`n`), `Escape` (focus tree), `j` to topic row 2, `Space`, `j`, `j`, `Space` (two topics selected), `t` (view toggles), assert coverage chips, `s` (split flips to per-document, assert `sum-articles` equals docs count), `m` (model panel focused, the tier radiogroup has focus), `Escape`, `g` -> URL is `/verify`; and `GET /api/jobs` shows one `run` job to `score2` |
| E4 | **Low-cohesion marker**: route-intercept `GET /api/scope/groups` to set one topic's `cohesion` below `params.low_cohesion` (the mock embedder does not guarantee one); assert exactly one `low-cohesion` badge, not on Unassigned and not on high-cohesion topics. The real unmodified rule is covered by C4/U8 |
| E5 | **Unassigned present**: topic view shows "Unassigned blocks" first with "Catch-all"; it can be selected and its block count equals `groups[].topics[0].block_count`; the structure view has no such row |
| E6 | **Model panel**: shows the five tasks and models from `GET /api/scope/models`; hardware text from the probe; `default_tier` highlighted; pull commands visible; (setup runs `POST /api/probe` once so a probe exists); Apply is enabled and does not run commands |
| E7 | **Reload restores selection**: select a subtree in structure view, reload the page, assert the same rows are checked, the same view is active (`?view`), same `sum-blocks`, same split mode |
| E8 | Subtree select: in structure view `Space` on a parent section checks all descendants (aria `mixed` -> checked) and `Space` again clears them |
| E9 | Sources panel: both fixture docs listed with page counts and "Ready"; the scanned-doc case is covered by C1 (mock project uses born-digital PDFs); OCR warning appears when `/api/sources` is intercepted to return `ocr_warning` |
| E10 | Jobs polling: intercept `/api/jobs?status=...` to return a running job for 3 polls then empty; progress bar is visible then disappears and no further polling requests are sent for 3 s |

CLAUDE.md: "Forgetting the scanned case". Module 8 is UI over already-scored data; the scanned fixture is exercised by seeding the e2e project with `scanned.pdf` too if the cached build is < 2 min (setup builds `clean.pdf`, `figures.pdf`, `scanned.pdf`; E9 then asserts the scanned doc shows the "Scanned" badge and OCR warning from the real API). Fall back to C1 only if the build is slower; record the choice in PROGRESS.md.

## 6. e2e seeding, build and CI

### 6.1 Seeding (`scripts/e2e-project.sh`, `scripts/e2e-serve.sh`)

1. `scripts/e2e-project.sh <cache_dir>` (repo root, bash): `cp` `tests/fixtures/project-a` (and `scanned.pdf` per §5.3) into `<cache_dir>/project`, then `uv run labor run <cache_dir>/project --to score2 --mock`. The probe is not run here; it is posted through the API in the E6 `beforeAll` (`POST /api/probe`). Idempotent: cache key = sha256 of `tests/fixtures/CHECKSUMS.json` + `git`-independent `ALGO_VERSION`s printed by `labor status --json`; if `<cache_dir>/.key` matches, skip. `<cache_dir>` = `frontend/e2e/.cache/` (gitignored).
2. Preconditions asserted by the script (exit 1 with a message): every doc `fresh` in `labor status --json`; >= 2 topics + Unassigned; >= 1 structure group with a parent (for E8); `selection` default non-empty.
3. `e2e-serve.sh` copies the cache to `os.tmpdir()/ml-e2e-<pid>/project` (so mutations never touch the cache), and serves that copy. `webServer` entries:

| Server | Command | URL |
|---|---|---|
| API | `scripts/e2e-serve.sh` (ends in `labor serve <tmp copy> --dev --mock --port 8765`) | `http://127.0.0.1:8765/api/project` |
| UI | `npm run dev` (Vite, proxies `/api`) | `http://127.0.0.1:5173` |

Playwright config changes: `workers: 1`, `fullyParallel: false` (one shared server and project; selection state is global), `retries: process.env.CI ? 1 : 0`, `trace: 'retain-on-failure'`, `webServer` becomes an array (API, UI). Because Playwright starts `webServer` entries before `globalSetup`, the API entry's command is the wrapper `scripts/e2e-serve.sh`, which builds or reuses the cache, copies it to a fresh temp dir and `exec`s `labor serve`; there is no `globalSetup` file. Specs may assume `GET /api/project` returns `mock: true`.

Why not run the e2e against `frontend/dist` through `labor serve` only: dev + proxy is what `playwright.config.ts` already does and gives source maps. A separate smoke `E0` (one test) runs against the built dist via `labor serve` (no `--dev`) in CI: loads `/scope`, asserts the tree renders (verifies static serving + SPA fallback for `/scope` reload).

### 6.2 Build and CI

| Step | Command |
|---|---|
| Build | `cd frontend && npm run build` (`tsc -b && vite build`) -> `frontend/dist`; `labor serve` mounts it (`find_frontend_dist()`), SPA fallback already handles `/scope` etc. |
| Unit/component | `npm test -- --run` (existing CI step) |
| e2e | new CI job `frontend-e2e` (needs the Python env): `astral-sh/setup-uv`, `uv sync`, `cd frontend && npm ci`, `npx playwright install --with-deps chromium`, `npm run e2e`. Chromium only. Upload `frontend/test-results/` on failure. Python tests are not run in this job. |
| Drift | existing `check-types-fresh` / `check-api-fresh` stay; G1/G2 additions regenerate `openapi.json` and `types.ts` |

Local first-time: `npx playwright install chromium`. `package.json` gains `"e2e": "playwright test"` (exists), `"test:ci": "vitest run"`.

### 6.3 Verification commands for the gate (pasted into `docs/PROGRESS.md`)

`cd frontend && npm run typecheck && npm test -- --run && npm run build && npm run e2e`, plus `uv run labor serve <project> --mock` smoke on `dist` (E0).

## 7. Risks and edge cases

| Case | Handling |
|---|---|
| Two docs with different `params.low_cohesion` | per-doc threshold (read from that doc's `GroupsFile`) |
| `topic_status = failed` for one doc | that doc contributes only Unassigned + notice; structure view normal |
| Regroup/threshold job finishes while the user has an in-flight PUT | the PUT response wins for `selection`; `groups` refetched; row cursor preserved by group id, falling back to index |
| Selection contains ids of a removed doc | server `normalize` drops them (`dropped`); UI ignores |
| Selection op replay after network drop | same `request_id` -> server returns stored outcome (idempotent) |
| Selection on a doc still grouping | its rows do not exist yet; `a` selects only groups present; the summary says "N documents still processing" |
| 0 selected | summary zeros; Confirm disabled with reason; `g` announces "Nothing selected" |
| Very long titles | truncate with `title` attribute; the tree row height is fixed so keyboard scroll-into-view (`scrollIntoView({block:'nearest'})`) is stable |
| Dark/light | not in scope; one light theme, system fonts |
| Concurrency of two browser tabs | last PUT wins; each tab refetches `selection` on window focus |
| Learning chips (findings: "why did this change") | not shown on Scope in module 8; `GroupsFile.learning_snapshot` != `baseline` renders a small "learned grouping: {snapshot}" tag in the doc heading row (no action), so module 10's disable control has a place to attach |

## 8. API gaps found (module 8 needs these)

| # | Gap | Needed because | Proposed exact change | Required? |
|---|---|---|---|---|
| G1 | No per-block data for the Scope screen. `GroupsFile` has block ids only; `figures` (type == figure) and `queued`/`numeric_queued` (status, `has_numeric_spec`) per selected block cannot be derived client-side | live counts without waiting for the PUT; pure unit tests (U6) | `GET /api/scope/blocks?doc=` -> `list[{doc_id, blocks: list[{id: BlockId, type: BlockType, status: BlockStatus, numeric: bool}]}]` from `data.machine_blocks(slug)` (the same statuses `scope_summary` uses); contract model `ScopeBlockRow` in `manuallabor/api/models.py`; `response_model` set; OpenAPI regenerated | Strongly recommended. Without it, §3.2 fallback applies and E2 asserts only `sum-blocks`/`sum-pages` optimistic values. |
| G2 | No bulk ops: "select all" and "clear" must be built from `select_group` per topic or a `select` with all ids | `a`/`n` keys; one round trip | add `SelectionOp.op` values `"select_all"` and `"clear"` (optional `doc_id`) handled in `ScopeService._apply` via `selectable_ids(groups)` | Optional (the client can use the existing ops) |
| G3 | `GET /api/scope/groups` returns every doc's full `GroupsFile` including `overlap`, `stragglers`, `title_sources`, which Scope does not render | payload size on 20 docs (tens of KB each) | none needed in v1; if too slow add `?slim=true` dropping `stragglers`, `overlap` | No |
| G4 | `/api/sources` gives `nodes` but no per-node timestamps or the doc `page_count` vs scanned flag beyond `kind`; fine for Scope. `ocr_warning` is a free-text string; the UI shows it verbatim and the scanned badge comes from `kind` | OCR quality warning | none | No |
| G5 | `POST /api/scope/confirm` returns a `JobInfo` but there is no persisted "scope confirmed" flag, so reopening `/verify` cannot tell whether Scope was confirmed | Scope -> Verify handoff correctness (SPEC §7.2 review scope = selected blocks) | none for module 8 (Verify reads selection directly: 07 §5, in-scope = selected). Noted for module 9. | No |

## 9. Post-gate fixes (2026-10-30, final pass)

| # | Finding | Fix | Test |
|---|---|---|---|
| P1 | A click made before `GET /api/scope/blocks` had answered left the optimistic summary at the server's old counts until the PUT answered (`apply()` can only recount with the block index). Playwright E2 failed under load with expected 8, received 0 while the PUT was held. | `useSelectionEngine` recounts the current optimistic selection once the block index arrives while writes are pending; the server's answer still wins when pending reaches 0. | `src/scope/liveCounts.test.tsx` |
| P2 | A project ingested from the CLI (every stage `missing`, no job) showed "Processing parse" forever with no button; Confirm was disabled. The README quick start dead-ended there. | Only Scope's stages (ingest to group) count: `clean` and `score2` run on Confirm, so a missing or stale one is "Ready" here. `sourceChip`: "Processing" only while a queued or running job's plan covers that manual (`JobInfo.doc` is just the last progress event, null while queued); otherwise "Not run yet: X" (missing) or "Needs a run: X" (stale). The Run button (same `to: group` plan as Re-run) appears when no job is running and a Scope stage is missing. | `src/scope/sourcesRun.test.tsx`; C1 assertion updated; e2e `scope.spec.ts` chip rule mirrors it |
