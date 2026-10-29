# Module 9 design: UI, Verify screen

Inputs: SPEC §5.1, §5.2, §7, §7.2, §9, §10; CLAUDE.md (module 9 gate: *20 blocks processed keyboard-only in a Playwright test; diff view correct; figure re-attach works*; UX-check subagent); findings (M3/M7: threshold slider is a view filter, never re-approves; approval invalidated by later text change; learning "why did this change" chip with per-rule disable); 07-api-state §2.3, §5.2, §5.3, §9, §12.5/12.12; 03-scoring §2, §4; 05-cleanup §5.3; 01-parse §2; **08-ui-scope (shell, router, data layer, hotkeys, e2e seeding: reused as-is except §7 below)**. Implemented routes read from `manuallabor/api/routers/{verify,figures,sources,jobs,learning}.py`, `manuallabor/state/{review,figures,data}.py`.

## 0. Decisions

| # | Question | Choice | Why |
|---|---|---|---|
| V1 | Page rendering: pdf.js or server PNG | **Server PNG** `GET /api/docs/{slug}/pages/{page}.png?dpi=150` (`dpi=300` when zoomed) | The server already renders and caches PNGs with PyMuPDF (`pages_view/`). Scanned pages are images anyway, so pdf.js adds nothing there. No ~1 MB pdf.js bundle or worker, no font differences between machines (stable Playwright runs), and the overlay uses the same PDF-point space as `Block.bbox`. What we give up is vector zoom and text selection. 300 DPI covers a 2x zoom of small figure text. Recorded as a SPEC §10 stack change with this reason. |
| V2 | Overlay technique | Absolutely positioned HTML `<button>`s over the `<img>`, in **percent of page size** (`left = x0/width*100%` etc.; `PageRef.width/height` in points, top-left origin, 01 §2) | No scale math on resize. Buttons give focus, roles and Playwright locators for free. |
| V3 | Threshold slider | View filter only (`view_threshold` on the cursor). Range **[project threshold, 1.00]**, step 0.01; at the project threshold value = `null` (off). Copy: "Showing {N} auto-approved blocks below {X}", or "Only blocks under the {T} threshold" when off. A "Show all" button sets 1.00. | Auto-approved blocks have `confidence ≥ threshold`, so only values above it add anything (07 §12.5). We draw it directly (right = more blocks) and do not invert it; the copy makes the meaning explicit. Statuses never change (findings M3). |
| V4 | Queue size | `useInfiniteQuery` pages of `limit=500`; `@tanstack/react-virtual@3` list with fixed 64 px rows | SPEC §9 asks for 1,000+ blocks. Module 8 deferred virtualisation; Verify needs it. |
| V5 | Write ordering | One **serial write queue** (`useVerifyWrites`) for actions, cursor PUTs and figure ops; each request carries a `request_id`; a network retry reuses the id (idempotent) | Server order == UI order even when keys are pressed faster than responses arrive. |
| V6 | Optimistic advance | Yes, for A/E(saved)/F/J. K is optimistic to `cursor.trail.at(-1)`. **The server `next` wins** on ack | Reviewer time (SPEC priority 2) without risking divergence. |
| V7 | Parser-disagreement highlights | Text pane: always, from a token diff of the scoring pair (`parserDiff.ts`, `diff@5.2.0` `diffWordsWithSpace`). Page: best effort. Disagreeing tokens are mapped onto `block.ocr_words` bboxes when those exist; otherwise the whole block rect gets a hatched "parsers disagree" style | 07 §12.12: blocks carry no per-parser word boxes. OCR words do exist on scanned pages and as background words, so the page highlight works where it matters most (scans). |
| V8 | Figure re-attach | Picker (keyboard and mouse); drag is **not** in v1 | The gate needs re-attach to work, and the picker is fully keyboard-accessible. Drag is optional in the brief. |
| V9 | Edit-mode drafts | Discarded on Esc; no persistence | An unsaved draft is not a decision. Keeps the state model small. |

New deps (pinned): `@tanstack/react-virtual@3.x`, `diff@5.2.0` (+ `@types/diff`), dev `@axe-core/playwright@4.x`.

## 1. Layout and components

Route `/verify` (full-width main; `JobsBar` + nav from the shell). Grid ≥ 1280 px: `StatusStrip` (row 1, full width); row 2 `Queue` 20rem | `SourcePane` 1fr | `ExtractedPane` 1fr | `FigureRail` 16rem; `ActionBar` sticky bottom. At 1024–1279 px the rail moves under `ExtractedPane`. Below 1024 px everything stacks in the order queue, extracted, source, rail.

```
src/verify/
  VerifyScreen.tsx  StatusStrip.tsx  Queue.tsx  QueueCard.tsx  SourcePane.tsx  ExtractedPane.tsx
  DiffView.tsx  WhyList.tsx  ParserCompare.tsx  LearningChip.tsx  EditConflictPanel.tsx
  FigureRail.tsx  FigurePicker.tsx  CropEditor.tsx  FlagDialog.tsx  ActionBar.tsx
  reasons.ts  diffSegments.ts  queueReducer.ts  geometry.ts  parserDiff.ts  labels.ts  sliderCopy.ts
  useVerifyWrites.ts  useVerifyState.ts     (pure *.ts each have *.test.ts)
```

| Component | Data | Renders | Behaviour |
|---|---|---|---|
| `StatusStrip` | `QueuePage.counts`, `docs`, cursor, `['project'].config.threshold` | `data-testid`: `cnt-queued` (= `pending − view_added`, gap G1), `cnt-auto` (`auto_approved`), `cnt-flagged` (`flagged_open`), `cnt-done` (`approved+edited`), `cnt-scope` (`in_scope`). Slider `<input type=range aria-label="Also review auto-approved blocks below">` with the copy from V3 (`testid=view-copy`). Sort `<select aria-label="Sort">`: Worst first / By page / Figures only. Save state `testid=save-state`: "Saved" / "Saving (n)" / "Not saved". Doc readiness chips for every `docs[]` with `state=pending` ("{slug}: preparing ({waiting_for})") or `stale` ("{slug}: re-scoring") | Slider changes are debounced 250 ms, then PUT cursor (all four fields), then the queue refetches with the new key. `[`/`]` step ∓0.05, clamped to [T, 1]; at T it sends `null`. `/` cycles the sort, then PUT cursor and refetch. |
| `Queue` | infinite queue pages + reducer state | `role="listbox" aria-label="Review queue"`, virtualised `QueueCard` options (`aria-setsize=total`, `aria-posinset`). A **pinned card** above the list when the current block is not pending (reached by K, click-to-jump, or reload), marked with its status. Footer row (not focusable): "N documents still preparing; their blocks appear here when ready". Empty state `testid=queue-empty` "All caught up" with links to `/agent` (when `flagged_open > 0`) and `/export` | Roving `tabindex`; ArrowUp/Down/Home/End browse, which sets current and PUTs the cursor (debounced 300 ms, through the write queue). Click = same. Prefetches the next page when the current index is within 50 of the loaded end. |
| `QueueCard` | `QueueItem`, `isCurrent` | id (mono), `p.{page}`, type, confidence `0.42` (or "n/a"), reason chips (`reasons.ts`), status chips: `changed since approval` (when `reasons[0]` is that stale name; it is shown as a status chip, not a reason), `re-scoring` (`stale_doc`), and status when not `queued` (`auto-approved`, `approved`, …) | `React.memo` on `(item, isCurrent)`. `aria-selected=isCurrent`, `data-testid="card-{block_id}"`, `aria-current` on the current card. |
| `SourcePane` | `BlockDetail.page` (`PageRef`), `['pageBlocks',slug,page]`, current block | `role="region" aria-label="Source page"`; `<img alt="Page {n} of {slug}">`; overlay buttons for every page block (`aria-label="{type} block {id}, {status}"`). Current block: 2 px outline `data-current`. Header/footer: dashed and `disabled`. Disagreement word highlights (V7) `data-testid=disagree-word`. DOCX (`render_url == null`): note "No page image for Word documents" plus the parser text. `PageRef.width == 0`: image only, no overlay | Click or Enter on a rect → `jumpTo(id)`. Jumping to an out-of-scope block (detail 422) shows a toast "Not in your selection". On mount and on current change the pane scrolls the rect into view. `z` toggles fit-width ↔ 2x (dpi 300). In crop mode (from the rail) it shows the figure's page with 4 corner handles (draggable; arrow keys move the focused handle by 1 pt, Shift by 10 pt). |
| `ExtractedPane` | `BlockDetail` | Header: id, type, `confidence`, status. Toggle `Text` / `Diff vs raw` (two `aria-pressed` buttons, `testid=view-text`/`view-diff`). Text = display text (`clean_text ?? raw_text`) with numeric emphasis. Diff = `DiffView` (§4). "Why this needs you" `WhyList`. `ParserCompare` (only when `parser_agreement` or `textlayer_vs_ocr` < 1). `LearningChip`. Figure block: figure image + caption + record fields instead of text, and Edit disabled ("Figure blocks are fixed via the rail") | `e`: an `<textarea aria-label="Edit block text">` replaces the text, prefilled with the display text and focused. Mod+Enter saves (POST `edit`). Esc cancels and focus returns to the current card. 409 `edit_conflict` → `EditConflictPanel`. 422 → inline alert, stay in edit. |
| `EditConflictPanel` | 409 body `conflict: EditConflict` | `role="alertdialog" aria-labelledby`: "This edit changes content", the violations list (`kind: 'raw' → 'clean'`), `numeric_changes` (e.g. `35 → 36`) emphasised, and the conflict `diff` through `DiffView`. Buttons **Confirm content change** (autofocus) and **Keep editing** | Enter on Confirm re-sends the same `text` with `confirm_content_change: true` and a **new** `request_id`. Keep editing / Esc returns to the textarea with the text intact. |
| `WhyList` | `BlockDetail.why` (server order: critical first, then value ascending) | `<ul aria-label="Why this needs you">`; per item: label (`labels.ts`), value `0.62`, a `critical` badge, the `detail` string verbatim (03 §2, e.g. `pymupdf vs docling 0.97; numeric: '+0.05' vs '±0.05'`). `has_numeric_spec` is shown as **Rule: always reviewed** (not a score). `stale` items come first as a status line. Auto-approved block shown through the slider: a line "Auto-approved ({c} ≥ {T}); shown by your view filter" | `rule`/`learning` kinds render in `LearningChip`, not here. |
| `LearningChip` | `BlockDetail.learning` | When `learned_rules` or `few_shot` is non-empty: chip "Why did this change? learned ({provenance})" that expands to one row per rule or example id, each with **Disable** | Disable → POST `/api/learning/items/{id}/disable`. On success: notice "Learning updated. Re-run cleanup to apply" with a button POST `/api/jobs {to:"score2", docs:[slug]}`. Never auto-runs (07 §9). |
| `FigureRail` | `['rail', articleId]` for each `detail.article_ids` (seeded from `detail.figures`) | `role="list" aria-label="Figures in this article"`; item: thumbnail (`image_url?v={record.phash}`), `figure_id`, caption, `record.extraction`, `attachment.rule`, confidence, status. Pending chip `testid=rail-pending` while its job runs. First element: button "Attach a figure…" | `g` focuses the rail. ArrowUp/Down move between items. Enter on the attach button opens `FigurePicker`. `x` on an item detaches it. `c` on an item opens crop mode (`CropEditor` + SourcePane handles). §5 has the flows. |
| `FigurePicker` | `['docFigures', slug]` (gap G2) | `role="dialog" aria-modal`; filter input (autofocus); `role="listbox"` of the doc's figures: thumbnail, id, caption, current articles + rule (`unattached` when none); checkbox "Also detach from its other articles" (default on) | ArrowDown/Up move from the input into the list. Enter attaches. Esc closes. |
| `CropEditor` | figure record (`bbox`, `page`), its block's `PageRef` | numeric form x0, y0, x1, y1 (pt) synced with the handles; validation (`geometry.validCrop`: x0 < x1, y0 < y1, inside `[0,width]×[0,height]`, ≥ 4 pt each side) | Save → PUT `/api/figures/{fid}/bbox` → job. Esc cancels. DOCX figures (`bbox == null`): crop disabled ("Word images have no crop box"). |
| `FlagDialog` | — | `role="dialog" aria-modal aria-label="Flag block"`; `role="radiogroup"` of 5 chips with key hints `1 Wrong text`, `2 Missing figure`, `3 Wrong grouping`, `4 Bad crop`, `5 Table structure` (`FlagCategory` order); note `<textarea aria-label="Note (optional)">`; Submit / Cancel | Focus starts on the radiogroup. Keys 1–5 select. Tab moves to the note. Enter submits when a category is set and focus is not in the note (no category: live message "Choose a category"). Mod+Enter submits from anywhere. Esc cancels. On submit, POST `flag` with `{category, note || null}`. A `bad_crop`/`missing_figure` flag on a figure block sets `target_id = figure_id`. |
| `ActionBar` | current item, write-queue state | Buttons `Approve (A)`, `Edit (E)`, `Flag (F)`, `Skip (J)`, `Back (K)` with `<kbd>` hints, plus `?` Help | A button press runs the same handler as its key. Edit is disabled for figure blocks; all are disabled when there is no current block. |

**Reason chips** (`reasons.ts`, pure): `reasonChips({why: ReasonIn[], hasNumeric, max = 3}) → {status: Chip[], reasons: Chip[], overflow: string[]}`, where `ReasonIn = {kind, name, value: number|null, critical: boolean}`.
1. `kind=stale` → status chip, never counted.
2. Critical failures: `kind=signal && critical && (value ?? 0) < 1`, sorted by value ascending (null keeps server order), then name.
3. The numeric rule: when `hasNumeric`, one chip "numeric spec" (tone `rule`). It is **always kept**, so criticals take at most `max − 1` slots.
4. Soft: `kind=signal && !critical && (value ?? 0) < 1 && name != has_numeric_spec`, sorted the same way, filling the remaining slots.
5. The rest go to `overflow` ("+N" chip whose `title` lists them).

Queue cards build `ReasonIn` from `QueueItem.reasons` with `critical = index < critical_reasons` (gap G3; fallback: critical iff name ∈ {faithfulness, figure_method}). `ExtractedPane` header chips use `detail.why` directly. Labels (`labels.ts`): parser_agreement "parsers disagree", textlayer_vs_ocr "text layer ≠ OCR", ocr_min "weak OCR word", ocr_mean "low OCR", reading_order_risk "reading order", table_consistency "table shape", garbage_ratio "garbled text", faithfulness "cleanup changed content", figure_method "figure crop", figure_resolution "low-res figure", figure_attach_rule "weak figure match", llm_verifier "verifier disagrees", has_numeric_spec "numeric spec".

## 2. Keyboard model (gate)

### 2.1 Entries added to `hotkeys.ts` (module 8's single map; new scopes per §7)

| Id | Key(s) | Scope | Action |
|---|---|---|---|
| `vApprove` / `vEdit` / `vFlag` / `vSkip` / `vBack` | `a` / `e` / `f` / `j` / `k` | verify | act on the current block (`e`: enter edit) |
| `vToggleDiff` | `t` | verify | Text ↔ Diff |
| `vFocusSource` | `s` | verify | focus the current block's rect in SourcePane |
| `vFocusRail` | `g` | verify | focus the rail's first element |
| `vSort` | `/` | verify | cycle the sort |
| `vViewDown` / `vViewUp` | `[` / `]` | verify | view threshold ∓0.05 |
| `vZoom` | `z` | verify | page zoom |
| `vEscape` | `Escape` | verify | close the open panel or mode (crop, picker, conflict), else focus the current card |
| `vBrowseNext` / `vBrowsePrev` / `vFirst` / `vLast` | `ArrowDown` / `ArrowUp` / `Home` / `End` | verifyQueue | browse (sets current) |
| `vSrcNext` / `vSrcPrev` / `vSrcJump` | `ArrowRight`,`ArrowDown` / `ArrowLeft`,`ArrowUp` / `Enter` | verifySource | move among rects in reading order / jump |
| `vRailNext` / `vRailPrev` / `vRailDetach` / `vRailCrop` | `ArrowDown` / `ArrowUp` / `x` / `c` | verifyRail | |
| `vSaveEdit` / `vCancelEdit` | `Mod+Enter` / `Escape` | verifyEdit, `allowInInputs` | save / cancel |
| `vFlagCat1..5` | `1`..`5` | flagDialog (modal) | pick a category |
| `vFlagSubmit` | `Enter` (not in note), `Mod+Enter` (`allowInInputs`) | flagDialog | submit |
| `help` | `?` | global (existing) | Help lists Verify keys from the same map |

Collision rules: `verify*` scopes are active only on `/verify`, so `a`, `t`, `s`, `g`, `j`, `k` do not clash with Scope's identically keyed entries. While a modal (`flagDialog`, picker, conflict) is open, its scope **shadows** the globals, so `1`–`4` pick a flag category instead of switching screens. Space is not bound. On Verify, `j`/`k` are Skip/Back as the SPEC says, not navigation; browsing uses the arrows.

### 2.2 Focus discipline
- On load, focus goes to the current card (from the cursor). If there is no current block, it goes to the first card.
- After **every** action (A, E saved, F submitted, J, K), focus moves to the new current card, optimistic first and then the server's. It is never left on a removed element. The live region (`role="status"`) announces "Approved {id}. Next: {id}".
- A/E/F/J/K work whenever focus is not in an input or textarea and no modal is open, whatever pane has focus. They act on the current block, never on the focused rect or rail item.
- Edit mode: the textarea swallows every key (module 8's input-ignore rule) except `Escape` and `Mod+Enter` (`allowInInputs`). A 409 moves focus to Confirm. Saving returns focus to the queue.
- Escape from the source pane, the rail, or any mode returns focus to the current card.
- Every interactive element has `focus-visible:ring-2`.

### 2.3 Exact sequence for the gate test (VE1)
Planning happens before any key press: `Q = GET /api/verify/queue?limit=2000` items; the template below is assigned to `Q[0..19]`. An `EDIT_OK` slot needs a non-figure block whose `detail.block.faithfulness?.passed !== false`. An `EDIT_409` slot needs a non-figure block. A `FLAG` slot accepts any block. When the block at a slot is ineligible, that role swaps with the nearest later `A` slot whose block is eligible. The plan is then fixed and logged. Keys only (`page.keyboard`), no `click`/`mouse`:

| Step | Block | Keys | Expected |
|---|---|---|---|
| 0 | — | `goto('/verify')`, wait for `card-{Q0}` focused | current = Q0 |
| 1–2 | Q0, Q1 | `a`, `a` | approved |
| 3 | Q2 (EDIT_OK) | `e`, `ControlOrMeta+End`, type `" "`, `ControlOrMeta+Enter` | edited, `faith_passed=true` (AE1: trailing whitespace) |
| 4 | Q3 | `a` | |
| 5 | Q4 (FLAG) | `f`, `1`, `Tab`, type `digit unclear`, `ControlOrMeta+Enter` | flagged `wrong_text`, note saved |
| 6 | Q5 | `a` | |
| 7 | Q6 | `j` | skipped (stays pending) |
| 8 | Q7 | `a` | |
| 9 | Q8 (EDIT_409) | `e`, `ControlOrMeta+End`, type `" 999"`, `ControlOrMeta+Enter`; conflict panel visible with a numeric change; `Enter` | edited, `faith_passed=false` |
| 10 | Q9 | `a` | |
| 11 | Q10 | `a`, then `k` (pinned card Q10 `approved`, focused), then `a` | re-approved; current = Q11 |
| 12 | Q11 | `a` | |
| 13 | Q12 (FLAG) | `f`, `5`, `Enter` | flagged `table_structure` |
| 14–20 | Q13…Q19 | `a` ×7 | approved |
| end | — | wait for `save-state` "Saved" | |

Assertions (API, as deltas against a pre-test snapshot): from `GET /api/decisions/export` (rows with `id >` the snapshot max), verify-screen kinds are `approve 16, edit 2, flag 2, skip 1, back 1`. `counts` delta: `approved +15, edited +2, flagged_open +2, skipped +1`. `GET /api/verify/cursor`: `current_block_id == Q20` and `trail.at(-1) == Q19`. In the UI: `card-{Q20}` is focused, and `card-{Q6}` is still in the list.

## 3. Data flow and state

### 3.1 Queries (all in module 8's `api/queries.ts`)

| Key | Endpoint | Cache rules |
|---|---|---|
| `['verify','queue',{sort,view}]` | GET `/api/verify/queue?sort&view_threshold&limit=500&offset` (infinite) | `staleTime: Infinity`. Refetched only on: sort/view change, job done, `refetchInterval: 3000` while any `docs[].state=="pending"` (readiness flips per doc mid-job), or Retry after a rollback. **Never refetched while the write queue is non-empty** (deferred until it drains). Next-page `offset` = the number of reducer items still pending (acted items are gone server-side too); merging dedupes by `block_id`. |
| `['verify','block',id]` | GET `/api/verify/blocks/{id}` | `staleTime: Infinity`, `gcTime: 60 s`. Prefetched for the next 2 items. Invalidated for X on X's ack, and all on job done. |
| `['pageBlocks',slug,page]` | GET `/api/docs/{slug}/pages/{page}/blocks` | `staleTime: Infinity`. The rect status is patched with `setQueryData` on ack. Invalidated on job done. |
| `['rail',articleId]` | GET `/api/articles/{id}/figures` | `initialData` from `detail.figures` (filtered by `attachment.article_id`); invalidated when the watched job is done |
| `['docFigures',slug]` | GET `/api/docs/{slug}/figures` (G2) | Fetched when the picker opens |
| `['jobs',id]` | GET `/api/jobs/{id}` | `useJobWatch(id)`: polls at 1 s while queued/running (shared change S4) |
| `['project']` | existing | threshold `T` |

Page images are cached by the browser by URL. When the next item's page differs from the current one, the next image is preloaded with `new Image()`. Figure thumbnails are cache-busted with `?v={record.phash}` (phash changes when a crop changes).

### 3.2 `queueReducer` (pure)
State `{items: QueueItem[], currentId: string|null, pinned: QueueItem|null, cursor: Cursor, counts, inflight: number, snapshots: Map<requestId, State>}`.

| Event | Effect |
|---|---|
| `loaded(page, replace)` | `replace` (first page, or a refetch) swaps in the items. Otherwise appends with `block_id` dedupe. `currentId` = cursor `current_block_id` if loaded, else keep. When it is set but not loaded, the screen loads more pages (≤ total/500) and then fetches its detail and shows it as `pinned` |
| `act(kind, X, rid)` | snapshot. Approve/edit/flag remove X from `items`; skip keeps it. Predicted current = the item after X in `items` (first item if X was pinned or last). `inflight+1` |
| `ack(rid, out)` | `currentId = out.next?.block_id ?? null`. If `out.next` is not in `items`, it becomes `pinned`. Set `cursor = out.cursor`, `counts = out.counts`, `inflight−1`, drop the snapshot |
| `fail(rid)` | restore the snapshot for `rid` and drop later snapshots. Pending writes queued after it are cancelled, and a toast "Not saved: {detail}" shows. Focus returns to X |
| `back(rid)` | predicted current = `cursor.trail.at(-1)` (pinned) or unchanged when the trail is empty (announce "Nothing to go back to") |
| `browse(id)` | `currentId = id`; the screen enqueues PUT cursor (debounced) |

### 3.3 Writes (`useVerifyWrites`)
- One FIFO promise chain. Each write is `{rid: crypto.randomUUID(), run()}`.
- A network error retries twice with the same `rid` (server replay returns the stored outcome). After that, or on any 4xx/5xx other than a handled 409, it goes to `fail`.
- Action body: `{kind, block_id, text?, confirm_content_change?, flag?, request_id}`. A cursor PUT always sends all four fields (`sort, view_threshold, doc_filter, current_block_id`).
- `save-state` = `inflight > 0 ? "Saving (n)" : lastFailed ? "Not saved" : "Saved"`. Every action is persisted server-side the moment its POST returns (SPEC autosave). Reload calls `GET /verify/queue`, whose `cursor` restores sort, view and current (SPEC resume).

### 3.4 Never blocking on model work
No Verify request triggers an LLM call (07 §5.1). Jobs appear in `JobsBar`. Blocks of a doc whose score2 is not done do **not** appear as cards (the server lists ready docs only). They are represented by the strip readiness chips and the queue footer, and they enter the list on the 3 s refetch while pending. Blocks of a `stale` doc (re-scoring after a re-attach or crop) remain actionable with a `re-scoring` chip. If the re-run changes their text, an earlier approval shows `changed since approval` (07 §2.3).

## 4. Diff view (gate)

Source of ops, first match:
1. Status `edited` → the latest `history` decision with `human_edit_diff` (the edit vs raw).
2. `block.faithfulness?.diff` (machine clean vs raw).
3. `clean_text == null` → message "No cleanup yet; text is raw" and the Diff toggle is disabled.

Ops with `raw == clean` everywhere render as "Identical to raw". The 409 panel renders `conflict.diff` with the same component.

`diffSegments(ops: DiffOp[]) → Segment[]`, with `Segment = {kind: 'equal'|'ins'|'del'|'move', ok: boolean, text: string, display: string, numeric: [number,number][], opIndex: number}`:

| Op | Segments (`text`) | Style class / `data-seg` |
|---|---|---|
| `equal` | `equal` (clean) | plain `pre-wrap` / `equal` |
| `delete`, allowed | `del` (raw) | grey strikethrough / `del-ok` |
| `delete`, violation | `del` (raw) | red bold strikethrough, `title="removed"` / `del-bad` |
| `insert`, allowed | `ins` (clean) | grey underline / `ins-ok` |
| `insert`, violation | `ins` (clean) | red bold underline, `title="added"` / `ins-bad` |
| `replace` | `del` (raw) then `ins` (clean), both taking the op's `allowed` | as above |
| `reorder`, allowed | `move` (clean, or raw when clean is empty) | blue, leading `⇅`, `title="moved (reading order)"` / `move-ok` |
| `reorder`, violation | `move` (same) | red, leading `⇅` / `move-bad` |
| any op with empty `text` | no segment | — |

- **Whitespace visualization** applies only in non-`equal` segments: `' '`→`·`, `'\n'`→`↵` followed by a real line break, `'\t'`→`→`, NBSP→`⍽`. `display` holds the visible form and `text` the original.
- **Numeric emphasis**: `numeric` = ranges of `/\d+(?:[.,]\d+)*/g` inside `text`, rendered `<mark class="num">` (bold) in every segment kind, in both Text and Diff views.
- **Invariants** (asserted in tests): the concatenated `raw` of ops in order equals `block.raw_text`, and the concatenated `clean` equals the shown clean text; every op yields segments carrying its `opIndex`; segment order follows op order.
- A legend sits under the diff. `aria-label`s on `del`/`ins` spans read "removed: …" / "added: …".

**VU2 table** (exact):

| # | Input op `(op, allowed, raw, clean)` | Expected segments `(kind, ok, text, display, numeric)` |
|---|---|---|
| 1 | `equal, T, "abc", "abc"` | `(equal, T, "abc", "abc", [])` |
| 2 | `delete, T, "-\n", ""` | `(del, T, "-\n", "-↵", [])` |
| 3 | `insert, T, "", " "` | `(ins, T, " ", "·", [])` |
| 4 | `delete, F, "35", ""` | `(del, F, "35", "35", [[0,2]])` |
| 5 | `insert, F, "", "36"` | `(ins, F, "36", "36", [[0,2]])` |
| 6 | `replace, F, "35 N·m", "36 N·m"` | `(del, F, "35 N·m", "35·N·m", [[0,2]])`, `(ins, F, "36 N·m", "36·N·m", [[0,2]])` |
| 7 | `replace, T, "\n", " "` | `(del, T, "\n", "↵", [])`, `(ins, T, " ", "·", [])` |
| 8 | `reorder, T, "Step 2.", "Step 2."` | `(move, T, "Step 2.", "Step·2.", [[5,6]])` |
| 9 | `reorder, F, "Then oil.", ""` | `(move, F, "Then oil.", "Then·oil.", [])` |
| 10 | `equal, T, "", ""` | `[]` |
| 11 | `insert, F, "", "\t"` | `(ins, F, "\t", "→", [])` |
| 12 | `equal, T, "0.25 mm ±0.05", …` | `numeric = [[0,4],[9,13]]` |

## 5. Figure re-attach (gate)

| Flow | Steps |
|---|---|
| Attach here | `g` → "Attach a figure…" → Enter → picker (`['docFigures', slug]`; the doc = `parse(articleId).slug`) → filter / arrows → Enter. Then: POST `/api/figures/{fid}/attach {article_id: current article, anchor_block_id: current block id unless it is a figure block, request_id}` → 202 `{override, job}`. If "also detach" is on, a POST `/detach` follows for each other article in the figure's `attachments` (same write queue). **Optimistic**: insert `{figure_id, record, attachment: {rule: "human", confidence: 1}}` into `['rail', article]` with `rail-pending`. `useJobWatch(job.id)`: on `done`, invalidate `rail`, `docFigures`, `verify/block`, `pageBlocks`, `queue`. On `failed`, roll back the optimistic insert and toast the job `error`. |
| Detach | focus a rail item, `x` → POST `/detach {article_id}` → optimistic remove (item greyed, `rail-pending`) → job watch as above |
| Persistence | Reload: the rail comes from `attach.json` via `GET /api/articles/{id}/figures`; rule shows `human` (05 §5.3 overrides re-applied every run). |
| Crop | `c` on an item (PDF figures only) → SourcePane switches to the figure's page (`record.page`; dims from that figure block's detail `page`) with handles at `record.bbox`, plus the `CropEditor` form → Save → PUT `/api/figures/{fid}/bbox {bbox, request_id}` → 202 `{job}` → job watch → rail refetch. The thumbnail URL changes through `phash`. Esc leaves crop mode and the SourcePane returns to the current block. |

If the article id of an override no longer exists after a split change, it lands in `overrides_stale` server-side (05 §5.3). The rail then shows nothing new, and the picker shows the figure's actual attachments.

## 6. Test plan

All from `frontend/`. Tooling, MSW factories and conventions follow 08 §5. New factories: `makeQueuePage(n)`, `makeBlockDetail(opts)`, `makeRailItem()`, `makeEditConflict()`.

### 6.1 Unit (`src/verify/*.test.ts`, `src/hotkeys.test.ts`)
| # | Test |
|---|---|
| VU1 | `reasonChips`: criticals first by value; numeric rule chip always present even with 3 criticals (2 criticals + rule); soft fill ascending; `has_numeric_spec` signal never duplicated as soft; stale → status chip only; overflow list; null values keep order; `critical_reasons` fallback |
| VU2 | `diffSegments`: the §4 table rows 1–12 exactly |
| VU3 | `diffSegments` invariants on 3 recorded real diffs (`clean.pdf` dehyphenation block, a header-removal block, an accepted reorder): raw/clean reconstruction, opIndex coverage |
| VU4 | whitespace `visualize()` and `numericRanges()` edge cases (`10A`, `±0.05`, `4471-A`, `1,250.5`) |
| VU5 | `HOTKEYS`: no key collision among overlapping scopes incl. Scope's (module 8 U1 extended with the verify scopes and modal shadowing); every entry has a label; `allowInInputs` only on Escape/Mod+Enter |
| VU6 | `queueReducer`: load/append dedupe; act removes (approve/edit/flag) vs keeps (skip); prediction; ack with a different `next` wins; ack with a non-listed next → pinned; fail restores and cancels later snapshots; back with empty trail; offset = pending count |
| VU7 | `geometry`: bbox → percent style; `validCrop` bounds; handle drag clamps |
| VU8 | `parserDiff`: pair choice order `(pymupdf,docling)`, `(ocr,ocr_alt)`, `(docx,docling)`; disagreement spans; mapping to `ocr_words` (order-preserving, unmatched skipped) |
| VU9 | `sliderCopy`: null → "Only blocks under the 0.85 threshold"; 0.95 with N=3 → "Showing 3 auto-approved blocks below 0.95"; clamp and step |

### 6.2 Component (`*.test.tsx`, MSW)
| # | Test |
|---|---|
| VC1 | `StatusStrip`: counts from `counts` (+G1), readiness chips, slider min = T, `[`/`]` debounced single PUT cursor with all 4 fields, `/` cycles sort and refetches |
| VC2 | `Queue`: 1,500 items render ≤ 60 option nodes; roving focus; arrows browse and PUT the cursor (debounced); `changed since approval` and `re-scoring` chips; pinned card; footer for pending docs; empty state links |
| VC3 | `SourcePane`: img `src` with `dpi=150`/`300` on `z`; a rect's percent style for a known bbox; current outlined; header/footer disabled; click and Enter call `jumpTo`; 422 toast; DOCX fallback; `disagree-word` boxes from `ocr_words` |
| VC4 | `ExtractedPane`: Text/Diff toggle and `t`; diff source choice (edited → `human_edit_diff`); why list order + detail strings + numeric rule line; edit: Mod+Enter posts `edit`; 409 → panel → Enter re-posts with `confirm_content_change:true`, the same text and a new `request_id`; Keep editing keeps the text; 422 alert; figure block: image shown, `e` disabled |
| VC5 | `LearningChip`: shown only with rules/examples; Disable posts the item id; re-run button posts `/api/jobs` |
| VC6 | `FigureRail` + `FigurePicker`: fields; picker lists doc figures with attachments; attach posts then the optimistic `human` + pending; also-detach posts one detach per other article; job done → refetch; job failed → rollback; `x` detach; `c` crop form validation and PUT bbox; thumbnail `?v=phash` |
| VC7 | `FlagDialog`: focus starts on the radiogroup; digits select (and do not navigate screens); Enter without a category announces; Tab → note; Mod+Enter submits `{category, note}`; Esc cancels; focus trap |
| VC8 | `VerifyScreen` integration: optimistic advance before the response; server `next` wins; 500 → rollback + toast + focus back; 3 fast `a` presses → 3 ordered POSTs with distinct ids; focus is on the current card after each action; `k` pins; job done → invalidations; queue not refetched while writes are in flight |
| VC9 | `ActionBar`: key hints present; clicks equal keys; disabled states |

### 6.3 Playwright `frontend/e2e/verify.spec.ts` (seeded mock project, 08 §6)
`beforeAll`: `resetSelection(request)` (shared helper, §7 S8), POST `/api/scope/confirm`, `waitJobsIdle` (≤ 180 s). Preconditions (the test fails with a message if any is unmet): queue total ≥ 30; ≥ 1 numeric queued block; ≥ 1 auto-approved in-scope block with confidence < 1; the `figures` doc has ≥ 2 articles and one figure attachable to an article it is not in. Tests run in this order, with assertions as deltas.

| # | Test (gate mapping) |
|---|---|
| VE1 | **20 blocks keyboard-only** (gate): the §2.3 sequence and assertions |
| VE2 | **Diff view correct** (gate): via the API pick a block whose `faithfulness.diff` has ≥ 1 non-equal op (prefer the `clean.pdf` `lubri-\ncation` block); PUT cursor to it, reload, press `t`. For each expected segment from `diffSegments()` (imported from `src/verify/diffSegments.ts`), the DOM has `[data-op-index=i][data-seg=…]` with `textContent == display`. The `lubri` block shows a `del-ok` segment `-↵` |
| VE3 | **Figure re-attach persists** (gate): via the API choose article B (with a queued block in it) and figure F not attached to B; PUT cursor to B's block, reload; `g`, Enter, type F's id, ArrowDown, Enter. The rail shows F with `human` + pending. Wait for the job to be done; reload; the rail item F shows rule `human`; `GET /api/articles/{B}/figures` contains F with `attachment.rule == "human"`; F's previous article no longer lists it. Then `x` detaches F → job done → reload → F is absent from B |
| VE4 | **Slider is a view filter**: let A1 = an auto-approved block with confidence c < 1; press `]` until the copy reads a value > c. `card-{A1}` appears, `view-copy` says "Showing N auto-approved…" with N ≥ 1, and `GET /api/verify/blocks/{A1}` status is still `auto_approved`. `GET /api/verify/cursor` `view_threshold` is persisted. `[` back to T removes A1 |
| VE5 | **Reload resumes**: `a`, `a`; note the focused card id; reload → the same card is focused and current, ExtractedPane shows that id, sort/view unchanged |
| VE6 | **Click-to-jump**: click another in-scope rect on the page → it becomes current (pinned if not pending) and `GET /api/verify/cursor` matches; keyboard variant `s`, `ArrowRight`, `Enter` does the same; a header rect is not clickable |
| VE7 | **Numeric approve**: PUT cursor to a queued `has_numeric_spec` block, reload, `a` → `GET /api/verify/blocks/{id}`: `block.status == "approved"`, `block.numbers_verified == true`, last `history[].numbers_verified == true` |
| VE8 | **Accessibility**: `@axe-core/playwright` on `/verify` (and with the flag dialog open) → no `serious`/`critical` violations; Tab through panes, where every focused element has a non-`none` outline/box-shadow; roles: `listbox` queue, `region` panes, `dialog` flag |
| VE9 | **Scanned case** (CLAUDE.md), when the seeded project includes `scanned.pdf` (08 §5.3; skipped otherwise with a reason): the page image loads for a scanned block, the why list shows `ocr_min`/`parser_agreement` details, and approve/edit work |
| VE10 | **Pending docs**: route-intercept `GET /api/verify/queue` to return one `docs[]` pending → readiness chip + footer shown, list still usable |

Gate commands (pasted into PROGRESS.md): `cd frontend && npm run typecheck && npm test -- --run && npm run build && npm run e2e`.

**UX-check subagent brief**: run VE1–VE10 against the dev server, then drive `/verify` by hand through Playwright. Confirm the SPEC §7.2 behaviours one by one (status strip counts, threshold, sorts, four panes, A/E/F/J/K, flag chips + note, numeric approve, autosave, resume) and report screenshots of the diff view, the conflict panel and the picker.

## 7. Shared-piece changes in module 8's shell

| # | File | Change |
|---|---|---|
| S1 | `router.tsx` | `/verify` → `VerifyScreen` (replaces `ComingSoon`) |
| S2 | `hotkeys.ts` | Scope union adds `verify`, `verifyQueue`, `verifySource`, `verifyRail`, `verifyEdit`, `flagDialog`, `picker`. Entry fields add `allowInInputs?: boolean`, `mod?: boolean` (Ctrl or Meta), `modal?: boolean`. §2.1 entries |
| S3 | `hooks/useHotkeys.ts` | (a) route scope `verify` is active on `/verify`; zone scopes come from `data-zone` (`queue`, `source`, `rail`, `edit`). (b) `allowInInputs` entries fire inside inputs/textareas. (c) `mod: true` entries require Ctrl or Meta, and other entries still ignore modified keys. (d) Modal shadowing: while an element `[aria-modal=true][data-hotkey-scope]` is open, only that scope + `Escape` fire (the globals `1`–`4` are suppressed) |
| S4 | `hooks/useJobsPolling.ts` | On job `done`, also invalidate the prefixes `['verify']`, `['rail']`, `['docFigures']`, `['pageBlocks']`. Export `useJobWatch(id)` (per-job query, 1 s polling while queued/running) |
| S5 | `api/client.ts` middleware | `ApiError` keeps the parsed body (`body: unknown`) so Verify can read the 409 `conflict` |
| S6 | `shell/Toast.tsx` + `useToast` (small React context) | Shared toasts (module 8 also needs "Selection not saved") |
| S7 | `shell/Help.tsx` | Groups entries by scope with headings; no per-screen code |
| S8 | `frontend/e2e/helpers.ts` (new) | `resetSelection(request)` (moved from `scope.spec.ts` beforeEach), `waitJobsIdle(request, ms)`, `api(request)` typed helpers; both specs import them |
| S9 | `src/test/handlers.ts` | Add the verify/figures/learning handlers and factories (§6) |
| S10 | `package.json` | deps from §0 |

No change to module 8's e2e seeding scripts. Verify's preconditions live in its own `beforeAll`.

## 8. API gaps (module 9 needs these from module 7)

| # | Gap | Exact change | Required? |
|---|---|---|---|
| G1 | No count of auto-approved blocks added by the view filter, so "Showing N auto-approved blocks below X" and the queued count are not exact without loading every page | `ReviewCounts.view_added: int = 0` (pending entries whose status is `auto_approved`), set in `ReviewService._scan` | Yes for exact copy (fallback: count loaded items, suffix "+" when `items.length < total`) |
| G2 | No list of a document's figures for the picker (only per-article rails) | `GET /api/docs/{slug}/figures` → `list[DocFigure{figure_id, block_id, record: FigureRecord, image_url, attachments: list[FigureAttachment], status: BlockStatus}]`, built from `attach.json` articles + `unattached` + sidecars, sorted by figure id; `DocFigure` model in `state/models.py`; OpenAPI regenerated | **Yes** (the picker gate) |
| G3 | `QueueItem.reasons` has names only, so the cards cannot tell critical failures from soft ones | `QueueItem.critical_reasons: int = 0` = how many leading `reasons` came from critical items (the why order already puts critical first) | Recommended (fallback in §1) |
| G4 | `view_threshold = 1.0` cannot show blocks with confidence exactly 1.0 (`confidence < view`) | In `_scan`: `shown` when `confidence < view or view >= 1.0` | Optional ("Show all") |

No other gaps: actions, cursor, detail (incl. `PageRef`, `why`, `parser_texts`, `history.human_edit_diff`, `learning`), page PNG/blocks, attach/detach/bbox, jobs and learning disable are all implemented as Verify needs them.

## 9. Open issues (resolved)

| # | Issue | Choice |
|---|---|---|
| O1 | pdf.js (SPEC §10) | Server PNG (V1); pdf.js not added |
| O2 | Slider direction vs SPEC "drag to 0" | Direct slider over [T, 1] with explicit copy and "Show all" (V3); recorded as a SPEC wording deviation |
| O3 | Page-level disagreement without per-parser boxes | OCR-word mapping when available, otherwise a hatched block rect (V7) |
| O4 | Acting on an approved block after K | Allowed (the server accepts any in-scope block); it writes a new decision, so a re-approve is logged twice by design (audit trail) |
| O5 | Edit of an `auto_approved` block shown by the slider | Allowed; it becomes `edited`. The slider never approves anything |
| O6 | Figure blocks in the queue | Shown (figures are in scope via attachment); `e` disabled; flag defaults `target_id` to the figure for `bad_crop`/`missing_figure` |
| O7 | Queue refetch vs optimistic state | No refetch while writes are in flight; the server `next`/`counts` from each ack are authoritative |
| O8 | Drag re-attach | Not in v1 (V8); the picker covers the gate |
| O9 | The plain edit in VE1 must pass faithfulness on any text | Trailing whitespace (AE1 strips text ends), only on blocks whose current text passes; the plan assigns slots by eligibility |
| O10 | e2e state shared with `scope.spec.ts` | `workers: 1`; Verify's `beforeAll` resets the selection, confirms and waits for jobs; all assertions are deltas |
