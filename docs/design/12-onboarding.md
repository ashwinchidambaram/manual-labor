# Module 12 design: onboarding, explanations and visible evidence

Inputs: SPEC §5 (signals, faithfulness, calibration), §7.1 to §7.4; CLAUDE.md; designs 08 (shell, Help, hotkeys, focus zones), 09 (Verify focus discipline, reason chips, WhyList), 10, 11 (export gate); PROGRESS M9 (late approve ack stole focus from the editor/dialog). User feedback: "could be better and a bit more intuitive ... a guide on how to use it or like tooltips". Coordinator additions: design for someone who has never seen the UI, and let them **build trust** by seeing evidence where they decide.

**Hard constraint.** Review semantics, the HOTKEYS map, the focus rules of 08 §1.3 / 09 §2.2 and all 55 Playwright tests stay unchanged. This module adds explanation; it does not move behavior.

## 0. Findings that shape the design

| # | Finding | Consequence |
|---|---|---|
| F1 | `/agent` and `/export` are still `ComingSoon` stubs ("arrives in a later module"). M10/M11 shipped API + CLI only (`/api/agent/*`, `/api/calibration`, `/api/export/status`, `POST /api/export`, `labor agent`, `labor export`) | A first-timer reaches a dead end at steps 3 and 4. A guide cannot explain a screen that does not exist, so this module adds two small read-mostly screens (§2.7) |
| F2 | Help (`shell/Help.tsx`) is a shortcuts-only modal, opened by `?` and by the header button; it restores the prior focus on close | Extend it; do not replace it |
| F3 | Playwright gives every test a fresh browser context, so a localStorage "seen" flag is always empty in e2e | The flag lives server-side; e2e seeds it (§3) so existing specs never see the panel |
| F4 | `Store.meta()/set_meta()` exist (table `meta`), outside the action log and the decision log | The natural home for a per-project UI flag; it never touches calibration or replay |
| F5 | Chips sit inside cards and rows asserted with `toHaveText` (e.g. `source-chip` = "Ready") | Tooltip text must never render inside the trigger (portal, render on open only) |
| F6 | Nav links are found by exact accessible name ("Scope", "Verify", "Agent") in vitest | The step indicator keeps those names; extra text is `aria-hidden` and goes into a description |
| F7 | `EditConflictPanel` is `aria-modal` without `data-hotkey-scope`, so `?` passes through it (08 rule: modal without scope lets only `help` through) | Unchanged. Help opens over it and restores focus to Confirm on close; covered by a test |
| F8 | `ReviewCounts` identity: `in_scope = queued + auto_approved + approved + edited + flagged_open`; `skipped` is a subset of queued/auto; `pending` includes view-filter additions | The reconciliation line uses this identity, not `pending` |
| F9 | `GET /api/scope/blocks` lists every block with `type` (incl. header/footer); topic groups incl. Unassigned partition the rest | "Nothing dropped" is computable client-side per doc |

## 1. Decisions

| # | Question | Choice | Why |
|---|---|---|---|
| O1 | Guide surface | **Docked, non-modal "Getting started" panel** (`<aside aria-label="Getting started">`, right edge, 22rem; it narrows the main grid instead of covering it, so the source page and editor stay visible) on first run; contextual: it shows the card for the current screen, with Previous/Next across all steps | A modal would take focus and shadow hotkeys (useHotkeys treats any `aria-modal` as a shadow). A panel lets the user read and act at once. Impeccable bans "modal as first thought" |
| O2 | Auto-open focus | The panel **never calls `focus()`** on open, on step change or on route change. It is outside every `data-zone`, rendered after `<main>` in DOM order, so existing Tab order and zone hotkeys are untouched | M9 history: any surprise focus request races with the editor/dialog |
| O3 | Re-open | `?` and the header Help button open Help (unchanged trigger, unchanged focus trap). Help gets two tabs: **Guide** (default) and **Keyboard shortcuts**. A "Show guide panel" button in the Guide tab closes Help and docks the panel | Keeps one hotkey and one dialog. `?` is already ignored in inputs, so it cannot fire mid-edit |
| O4 | Tooltip mechanism | A small **`<Hint>`** component, not native `title` | `title` does not show on keyboard focus, has a 1 s+ OS delay, is invisible on touch and cannot hold a hotkey `<kbd>`. `<Hint>`: shows on hover (400 ms) and on `:focus-visible`, `role="tooltip"` rendered in a portal only while open, trigger gets `aria-describedby` while open. Esc hides it via a passive capture listener **without** `preventDefault`, so Esc still reaches `focusTree`/`vEscape`. ~60 lines, no library |
| O5 | Hidden vs visible | **Visible first.** Anything a first-timer needs to decide (what the slider does, why a block is queued, what a check means, what export refuses) is inline text. Hints only add the hotkey and a longer definition | Coordinator brief: do not hide decision-critical meaning behind hover |
| O6 | Non-focusable chips | Not made focusable (that would add tab stops and break roving focus and the ux-scope / VE8 tab walks). Their meaning is reachable by keyboard through the inline WhyList / ChecksList and the Help **Glossary** (generated from the same `hints.ts`) | Keyboard parity without changing focus order |
| O7 | Step indicator | Enhance the existing `<nav aria-label="Screens">` links: visible step number + state ("done", "here", "next", "locked: 2 flags"). Links keep `aria-label="Scope"` etc.; state in `aria-describedby` | One nav, no duplicate link names (F6) |
| O8 | Persistence | `GET/PUT /api/ui/guide` over `meta['ui.guide_seen']`; fallback localStorage (§3) | Per project, survives browsers, not an action |
| O9 | Content source | `src/onboarding/guide.ts` (steps, guarantees) and `src/onboarding/hints.ts` (control id → meaning, optional `HotkeyId`). `docs/USER_GUIDE.md` is generated from these plus `hotkeys.ts` | One source; drift is a failing test |
| O10 | Styling | Existing Tailwind tokens (slate neutrals, blue-600 focus ring, amber warnings, red violations). No new colors, no icons library | Consistency with modules 8/9 |

## 2. Components and interfaces

New folder `frontend/src/onboarding/`: `guide.ts`, `hints.ts`, `Hint.tsx`, `GuidePanel.tsx`, `useGuideState.ts`, `StepNav.tsx` (logic only; renders inside AppShell's nav), `reconcile.ts`, `ChecksList.tsx`, `glossary.ts`. Screens: `agent/AgentScreen.tsx`, `export/ExportScreen.tsx`.

### 2.1 `guide.ts` (data, pure)
```ts
export const GUIDE_VERSION = 1;                       // bump when content changes materially -> shown once more
export interface GuideStep { id: "scope"|"verify"|"agent"|"export"; route: string; title: string;
  what: string; do: string[]; keys: HotkeyId[]; trust: string[] }
export const GUIDE_STEPS: GuideStep[]; export const GUARANTEES: { claim: string; how: string }[];
```
Step content, in the order the user meets it (copy drafts; final copy reviewed in the shape brief):
- **Scope.** "Choose what goes into your knowledge base." Selection = blocks that will become articles. *Suggested topics* and *Document structure* are two views of the **same blocks**; switching never changes the selection, and the other view shows % coverage. Low cohesion = the topic mixes subjects; check it. Unassigned = blocks no topic claimed; nothing is silently dropped. "Estimated review" = how many selected blocks will need you. Confirm (`G`) starts scoring and opens Verify immediately.
- **Verify.** The queue lists only blocks the machine is unsure about, worst first. Each card says why (reason chips). Blocks with numbers, units or part numbers are **always** queued: OCR mistakes in numbers are likely and a language model cannot see them. `A` approve (on a numeric block this records "numbers verified by you"), `E` edit (`Ctrl/Cmd+Enter` saves), `F` flag with a category, `J` skip, `K` back. `T` shows the diff against the raw parse. The slider only **shows** auto-approved blocks for a second look; it never changes their status. Figures: `G` focuses the rail, "Attach a figure…" re-attaches, `X` detaches, `C` adjusts the crop.
- **Agent.** Flags you raised can be handed to a model, one fresh call per item. Every proposal is re-checked by the same deterministic checks; failures are shown, not hidden. You accept, edit or reject; rejected items return to the queue with what was tried. Calibration shows how often you edited blocks at each confidence level and suggests a threshold; it never changes it for you.
- **Export.** Unlocks when no flag is open and nothing in scope is still queued. If it is locked, the screen lists exactly what blocks it and links to each. Overrides are allowed, require a reason, and are written into `manifest.json`.

`GUARANTEES` ("How it works", shown in the guide and Help, stated plainly): (1) Parsing, IDs, scoring, the faithfulness check and assembly are deterministic code; the same file gives the same result. (2) Cleanup may only join hyphenated lines, fix whitespace, remove headers/footers, normalise bullets and fix reading order; any other change to characters or numbers fails the faithfulness check and the block is queued with the diff. (3) Confidence comes from disagreement between independent sources (two parsers, text layer vs OCR, a separate verifier); no model rates its own output. (4) Every model output is validated before you see it. (5) Learning from your edits is visible per block ("Why did this change?") and can be disabled per rule or reset. (6) Counts reconcile on every screen, so you can see nothing was dropped.

### 2.2 `GuidePanel`
Props: `{ step: GuideStep; onPrev; onNext; onHide; index; total }`. Contents: step title, one-paragraph *what*, a numbered *do* list with `<kbd>` keys, a "Why you can trust this" sub-list, and footer buttons **Previous / Next / Hide guide**. Next on the last card says "Done". Hide → `PUT {seen: true}`. If `document.activeElement` was inside the panel when it hides, focus moves to the header Help button (stable, outside the review focus machinery); otherwise focus is not touched. The panel follows the route: arriving on `/verify` shows the Verify card unless the user paged manually in the last 5 s.

### 2.3 Help dialog changes (`shell/Help.tsx`)
Accessible name becomes "Help" (one vitest locator in `tree.test.tsx` updated). `role="tablist"`: **Guide** (all four steps + How it works + "Show guide panel") and **Keyboard shortcuts** (today's content, unchanged rendering) and **Glossary** (every entry of `hints.ts`). Left/Right switch tabs (local keys, added to `LOCAL_KEYS` so Help documents them). Focus trap, `Esc`/`?` close and focus restore are unchanged. Opening `?` from Verify shows the Guide tab scrolled to the Verify step.

### 2.4 `Hint` and `hints.ts`
`<Hint id="threshold"><input …/></Hint>` clones the single child, adding handlers and `aria-describedby` while open. `HINTS: Record<HintId, { text: string; hotkey?: HotkeyId }>`; the bubble shows `text` and, when set, `displayKey(HOTKEYS[hotkey].keys[0])` (never a literal key in copy). Named controls that get a Hint (the test list counts these 16): nav links (4), header Help, view toggle, split control, select all/none, Confirm, Sources "Add documents", model "Apply tier", Verify slider, sort select, Text/Diff toggle, each ActionBar button, rail "Attach a figure…", Export button, override reason. Non-focusable hover-only hints: reason chips, status chips, cohesion, coverage, `numbers_verified` badge, attach-rule badge, learning chip, method badge. Hints never render on touch-only devices (no hover, no focus) and never for disabled buttons' disabled reason, which is shown inline instead.

### 2.5 Trust at the point of decision
- **ChecksList** (ExtractedPane, under "Why this needs you"): "Checks on this block", one row per deterministic check with pass/fail text, never colour only: *Faithfulness* (`passed`, alignment ratio as %, violation count by kind: insertion / deletion / numeric mismatch / reorder), *Numbers preserved* (pass iff no `numeric_mismatch`), *Parsers agree* (`parser_agreement`), *Text layer matches OCR* (`textlayer_vs_ocr`, when present), *Figure attach rule* (figure blocks). Data: `block.faithfulness`, `block.signals`; missing data renders "not run yet", never "passed". A one-line fixed sentence above it: "Cleanup can only fix spacing, hyphenation, headers and reading order. Any other change is caught here and shown as a diff."
- **Provenance line** (ExtractedPane header): `{filename} · page {n} · block {id} · parsed by {parser_texts keys}`; Text/Diff toggle labelled "Original vs cleaned".
- **Reason chips** keep `reasons.ts`; WhyList item labels gain the plain sentence from `hints.ts` next to the existing `detail` string. The numeric rule line reads "Rule: blocks with numbers are always reviewed by a person".
- **`numbers_verified`**: after approving a numeric block the card and header show "Numbers verified by you" (from `block.numbers_verified`).
- **Reconciliation** (`reconcile.ts`, pure):
  - `reconcileDoc(blockIndex, topicGroups) → { parsed, headerFooter, inTopics, unassigned, missing: BlockId[] }`; Scope shows per doc "142 parsed = 12 headers/footers (excluded) + 118 in topics + 12 unassigned".
  - `reconcileReview(counts) → { inScope, queued, auto, done, flagged, skipped, ok }` with `queued = in_scope − auto − approved − edited − flagged_open`; Verify strip shows "In scope 300 = 40 to review + 200 auto-approved + 50 done + 10 flagged".
  - If an identity fails (`missing.length > 0` or `queued < 0`), show an amber `role="note"` "Counts do not add up ({detail}). Nothing was changed; please report this." Honest failure beats a hidden one.

### 2.6 Empty and first states (actionable copy, existing test ids kept)
| Screen / state | Shows |
|---|---|
| Scope, no documents (`scope-empty`) | Adds: "Manual Labor turns PDF/DOCX manuals into a reviewed knowledge base. Step 1: add documents." + Add documents |
| Scope, docs parsing | Per-doc chip with node + JobsBar progress, and "You can choose topics as soon as a document is ready; nothing needs to finish first" |
| Scope, nothing selected | Confirm disabled with inline reason "Select at least one topic or section (Space on a row, `A` for all)" |
| Verify, before confirm (no scored docs) | "Nothing to review yet. Confirm your scope on the Scope screen (`1`, then `G`)." + link |
| Verify, scoring running | Queue footer (existing) + "Blocks appear here as each document finishes scoring. You can start now." |
| Verify, empty (`queue-empty`) | "All caught up: {done} reviewed, {auto} auto-approved, {flagged} flagged." Then the next step: "Hand {n} flags to the Agent" or "Ready to export" |
| Agent, no open flags | "No open flags. Flag a block in Verify (`F`) when the text, figure, grouping or table is wrong." |
| Export locked | §2.7 |
| Job failed | JobsBar keeps the error; adds "What now": Retry (POST same plan) or "See log" (`GET /api/jobs/{id}/log`, first 20 lines) |

### 2.7 Agent and Export screens (replace stubs; read-mostly)
- **ExportScreen**: `GET /api/export/status`. Locked: heading "Export is locked", the two reasons as counts with links ("{open_flags} open flags: resolve in Agent or Verify", "{queued} blocks still to review: go to Verify"), the blocker list (first 50 ids, each a link that PUTs the cursor and opens Verify), "Why: the export only contains text a person or the checks have accepted." Override form: reason (required) → `POST /api/export/override`; listed overrides with "recorded in manifest.json". Unlocked: Export button → `POST /api/export` (409 renders the same locked view from the body), job in JobsBar, then `summary` (articles, figures, pages covered, review stats, sha256) and Download.
- **AgentScreen**: open flags (`GET /api/flags`), proposals list read-only with per-check pass/fail (`GET /api/agent/proposals`), calibration card (`GET /api/calibration`: buckets, suggestion and `suggestion_detail`, "never applied automatically"), and Run agent pass (`POST /api/agent/run`). Accept/Edit/Reject per proposal reuse the existing endpoints. Keyboard review of proposals is out of scope (O-Q3).
Both keep a "Back to Scope" link for the existing App.test.

## 3. Data flow and persistence

`GuideState { seen: bool, seen_at: str | null, version: int }` (Pydantic in `manuallabor/api/models.py`; OpenAPI + generated types regenerated). `version` is the server's `GUIDE_VERSION`. `GET /api/ui/guide` reads `meta['ui.guide_seen']`, a JSON value `{"version": int, "seen_at": ts}`: `seen = (stored version == GUIDE_VERSION)`, `seen_at` = the stored timestamp (null when unseen), so a `GUIDE_VERSION` bump makes `seen` false and shows the guide once more. `PUT /api/ui/guide {seen: bool}`: true stores `{"version": GUIDE_VERSION, "seen_at": now}`; false clears the key (stored as the empty string, read as unseen). Not an action: no `actions` row, not in decisions export, calibration or the zip. The API test fakes implement `meta`/`set_meta`/`tx`/`now` in memory.

`useGuideState()` (Query key `['guide']`, `staleTime: Infinity`): `open = !data.seen`. Fallback when the GET fails (non-404 error or the endpoint is missing on an older server): localStorage key `manuallabor.guide.v{GUIDE_VERSION}.{project.root}`, read and written in try/catch; if storage throws, the panel shows once per page load and Hide holds for the session. Documented in USER_GUIDE.md ("Reset the guide": Help → Guide → "Show guide panel", or `PUT /api/ui/guide {"seen": false}`).

e2e: new `e2e/global-setup.ts` PUTs `{seen: true}` on 8765 and 8766 before any spec, so the 55 existing tests run with the panel hidden. `onboarding.spec.ts` sets it to null in `beforeEach` and restores it in `afterAll`.

## 4. Focus and keyboard invariants (the contract this module must not break)
1. No onboarding code calls `focus()` except: Help's existing open/restore; Hide when focus was inside the panel (→ Help button).
2. The panel and Hints are outside all `data-zone`s, carry no `aria-modal`, and register no hotkeys.
3. `HOTKEYS` gains no entries; `LOCAL_KEYS` gains the Help tab arrows and nothing else.
4. Hint Esc listener is passive; existing Esc handlers run.
5. Hint bubbles live in a portal and exist only while open (F5); `getByText` strictness and `toHaveText` on chips are unaffected.
6. Nav link accessible names unchanged (F6).

## 5. Edge cases
- Guide open while the user starts typing in the editor: the panel stays; nothing moves focus. Step change on route change does not re-render the editor.
- Two tabs: the second sees `seen` on next refetch (window focus); hiding in one tab is not pushed live (acceptable).
- Narrow screens (< 1024 px): panel becomes a bottom sheet (max 40vh, scrollable), still non-modal.
- Scanned project: guide Verify card mentions "Scanned pages: text comes from OCR, so more blocks are queued"; ChecksList shows `ocr_min`.
- DOCX blocks: provenance says "Word document, no page image"; ChecksList omits text-layer-vs-OCR.
- `GUIDE_VERSION` bump: shown once more, starting at the current screen.
- Mock project: panel adds one line "Mock models: results are placeholders" when `project.mock`.

## 6. `docs/USER_GUIDE.md`
Generated by `npm run gen-guide` (`scripts/gen-guide.ts`, run with `tsx`) from `GUIDE_STEPS`, `GUARANTEES`, `HINTS` and `HOTKEYS` (grouped by `SCOPE_TITLES`, keys via `displayKey`), with a fixed header "Generated from frontend/src; edit there". Sections: Getting started (4 steps), How it works (guarantees), Keyboard shortcuts, Glossary, Reset the guide. Recorded in PROGRESS with the other generator commands.

## 7. Test list
**Vitest**
- U1 `guide.test.ts`: every `GuideStep.keys` id exists in `HOTKEYS`; steps in route order; no literal single-key strings in copy (keys only via ids); no em dashes in copy.
- U2 `hints.test.ts`: every `HintId` has non-empty text; every `hotkey` exists; every Hint used in source (`grep`-style import scan) is registered; Glossary renders every entry.
- U3 `userGuide.test.ts`: generated markdown === committed `docs/USER_GUIDE.md` (drift fails); shortcut table rows === `Object.values(HOTKEYS)` count.
- U4 `reconcile.test.ts`: doc identity with headers, unassigned and a missing id; review identity incl. skipped and view-filter additions; negative queued → `ok=false`.
- U5 `Hint.test.tsx`: shows on focus-visible and hover, not inside the trigger, `aria-describedby` set only while open, Esc hides and the event is not `defaultPrevented`.
- U6 `GuidePanel.test.tsx`: auto-open does not change `document.activeElement`; Hide PUTs the version; Hide from inside moves focus to Help; route change switches step.
- U7 `useGuideState.test.ts`: server flag wins; GET failure → localStorage; storage throwing → session-only.
- U8 Help: tabs, Left/Right, Guide default, shortcuts tab unchanged content, focus restore; `?` while the conflict panel is open restores focus to Confirm (F7).
- U9 ChecksList: pass/fail/not-run rows from fixtures, numeric mismatch → "Numbers preserved: failed".
- U10 ExportScreen/AgentScreen: locked view from status and from a 409 body; override posts reason; summary + download; empty agent state.

**Playwright `e2e/onboarding.spec.ts`**
- OB1 Fresh project: panel visible on `/scope`, focus is in the tree (unchanged 08 rule), hotkeys `j`/Space/`t` work with the panel open.
- OB2 Hide → reload → panel absent; `GET /api/ui/guide` returns the version.
- OB3 `?` opens Help on the Guide tab; Esc closes and focus returns to where it was.
- OB4 Never steals focus mid-edit: panel open on `/verify`, `e`, type, navigate guide via mouse clicks on Next, keep typing; the textarea keeps focus and the text is intact; `?` typed in the textarea inserts "?".
- OB5 Tooltips: focusing each of the 16 named controls shows a `role=tooltip` with the registered text (and key when set).
- OB6 Step nav shows "here" on the current route and Export "locked" with the open flag count from the API.
- OB7 Hotkey table in Help and USER_GUIDE.md rows match `HOTKEYS`.
- OB8 Reconciliation lines equal the API numbers on Scope and Verify.
- OB9 Export locked view lists blockers from `/api/export/status`; a blocker link opens that block in Verify.
- OB10 axe on `/scope` and `/verify` with the panel open and with a tooltip open: no serious/critical issues.
- **All 55 existing Playwright tests pass unchanged** (with global setup seeding the flag). Vitest changes to existing tests are limited to the Help dialog name (`tree.test.tsx`) and anything the replaced stubs require in `App.test.tsx`/`panels.test.tsx`; each listed in the PR.

Gate: `cd frontend && npm run typecheck && npm test -- --run && npm run build && npm run e2e` (65 tests) plus `uv run pytest -q tests/api -k guide`, and a UX-check subagent that plays a first-time user on a fresh project with the panel on, reporting where they stalled.

## 8. Draft PRODUCT.md (for confirmation via `impeccable teach`)
```md
# Product
## Register
product
## Users
Technicians and documentation owners turning equipment manuals (PDF, scanned PDF, DOCX) into a knowledge base an AI agent will answer from. Often first-time users of the tool, reviewing for an hour at a desk, keyboard-first once they learn it. They are accountable if a torque value is wrong.
## Product Purpose
Get a faithful, reviewed knowledge base out of messy manuals with the least human review, and show the reviewer why each decision is safe.
## Brand Personality
Plain, exact, accountable. Calm like a good checklist; never chatty or celebratory.
## Anti-references
Consumer onboarding carousels and confetti; AI products that show a single "confidence" number with no reason; dark "hacker" dashboards; marketing gradients.
## Design Principles
1. Show the evidence, not a verdict. 2. Say what will happen before it happens. 3. Never hide a count: totals reconcile on screen. 4. Explanations live where the decision is. 5. Keyboard first, mouse equal.
## Accessibility & Inclusion
WCAG 2.2 AA; visible focus everywhere; never colour only; works at 200% zoom; screen-reader names for every control.
```

## 9. Draft shape brief (for confirmation via `impeccable shape` before any UI change)
1. **Feature summary**: make Manual Labor self-explanatory to a first-time user and show the evidence behind every review decision, without changing review semantics or keys.
2. **Primary user action**: understand why a block is in front of them and decide with confidence.
3. **Design direction**: Restrained (existing slate neutrals, blue-600 focus, amber warn, red violation). Scene: "a maintenance engineer at a desk under office light, checking a scanned manual against its extraction for an hour". Anchors: a code-review diff view, an aircraft checklist, a bank statement that adds up.
4. **Scope**: production fidelity; Scope, Verify, Agent, Export, Help; keyboard and mouse.
5. **Layout**: guide docked right, never covering the source page or editor; trust text directly under the thing it explains; reconciliation lines in the status strips.
6. **Key states**: §2.6 table plus guide open/hidden, tooltip open, counts mismatch.
7. **Interaction**: §2.2 to §2.4 and §4.
8. **Content**: §2.1 copy, `hints.ts`, empty-state copy; no em dashes, no exclamation marks.
9. **References**: onboard.md, ux-writing.md, interaction-design.md, cognitive-load.md, clarify.md.
10. **Open questions**: §10.

## 10. Open questions (recommended answer)
- Q1 Auto-open the panel on first run, or only show a "New here? Open the guide" banner? **Auto-open docked panel**; it is non-modal and one click hides it for good.
- Q2 Rename the Help dialog from "Keyboard help" to "Help" (one vitest locator)? **Yes**; the dialog is no longer only shortcuts.
- Q3 Agent screen depth: read-mostly with mouse Accept/Edit/Reject, or full keyboard review now? **Read-mostly now**; keyboard proposal review is its own module (13) with its own UX check.
- Q4 Persist "seen" per project or per user? **Per project (meta table)**; a new project is a natural moment to re-read, and the panel is one click to hide.
- Q5 Show the reconciliation line always or only on mismatch? **Always**; it is the cheapest trust signal and is one line.
- Q6 Should tooltips appear on touch? **No**; everything decision-critical is inline (O5), Glossary covers the rest.
- Q7 Export override in this module or later? **This module**: SPEC §7.4 requires it and the API exists; without it a locked export is a dead end.

## 11. Resolutions (orchestrator, 2026-10-29)

Approved with the recommended answers: Q1 auto-open the docked panel on first run; Q2 rename the dialog to "Help";
Q3 Agent screen read-mostly with mouse Accept/Edit/Reject, keyboard proposal review deferred to module 13;
Q4 "seen" per project in the meta table with a localStorage fallback; Q5 reconciliation line always shown;
Q6 no tooltips on touch; Q7 export override form in this module. Implementation order: (a) backend `GET/PUT /api/ui/guide`
+ OpenAPI regen (no UI); (b) UI after the Impeccable shape brief in §9 is confirmed by the user; (c) UX check as a
first-time user; (d) fresh review. All 55 existing Playwright tests stay green throughout.
