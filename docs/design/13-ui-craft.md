# Module 13 design: UI craft (friendly, guided, trustworthy)

Inputs: PRODUCT.md (voice and principles 1 to 8), SPEC §7 (UI contract), `docs/design/12-onboarding.md` §4 (focus and keyboard invariants), `frontend/src/hotkeys.ts`, the live app on the demo project (`project-a`, mock models) at 1440px and 720px, and the Playwright suite in `frontend/e2e/`.

Owner direction (verbatim): "I want something that has a friendly and approachable feel, is extremely easy for a human to use, builds trust, guides a user through the process".

Method: Impeccable context loader (PRODUCT.md found, register `product`, no DESIGN.md), then `audit` on the live app, then `shape`. Image generation is not available in this harness, so the visual-direction probe step is replaced by two static HTML mocks (see §3).

**Hard constraint (unchanged from M12).** Review semantics, the `HOTKEYS` map, the focus rules of 08 §1.3 / 09 §2.2 / 12 §4, and the trust evidence (reasons, checks, counts, source page, diff) stay. This module changes how things look and read, not what they do. Every test id survives; the control names and copy strings the suite asserts are listed in §5, and only the ones listed there change.

**Status.** The brief in §2 is a proposal. Per Impeccable, it becomes binding only when the owner answers §7.

---

## 0. Landscape

| Surface | What a first-time user sees today |
|---|---|
| Shell | Wordmark, project name, amber "mock models" pill, four numbered tabs (current one is a black pill marked "here"), amber "locked: 216 to review" next to Export, Help button |
| Scope | Three columns (Sources 288px, topic tree, summary + models) plus a 350px "Getting started" guide column of prose. 31 topic rows, all at "100% selected" |
| Verify | Status strip of five raw counts, slider at its far left, sort select, a reconcile equation; queue of 216 cards titled by truncated block ids; extracted text; a 400px page render; the guide column again; action bar |
| Agent | Prose paragraphs under three headings, every one empty (0 flags, 0 proposals, 0 decisions); disabled button |
| Export | "Export is locked", 20 raw block ids as chips, an "Export anyway" override form with a textarea, open by default |

Impact radius of this module: every screen, the shell, `onboarding/*` (guide, hints, glossary copy), `verify/labels.ts` and `reasons.ts` (copy only), `scope/*` row and summary components, and a Tailwind token layer that does not exist yet. One server contract addition is needed for the human card title (§2.8.3).

---

## 1. Audit

### 1.1 Health score

| # | Dimension | Score | Key finding |
|---|---|---|---|
| 1 | Accessibility | 2 | Visible focus, real roles and full keyboard coverage, but at 720 CSS px (200% zoom, which PRODUCT.md requires) Verify becomes one 14,000px column: the queue fills the viewport and the text and page are never on screen together |
| 2 | Performance | 3 | Queue is memoised and virtualised; fine for 216 items. The queue container is 13,824px tall inside the document scroll instead of its own scroll area |
| 3 | Responsive | 2 | Desktop-only grid with fixed pane widths; acceptable for a desk tool, except for the zoom case above |
| 4 | Theming | 1 | No tokens: `tailwind.config.js` extends nothing, `index.css` is three `@tailwind` lines, colour is raw `slate`/`blue`/`red`/`amber`/`violet` classes in components |
| 5 | Anti-patterns | 3 | No slop tells (no gradients, glass, hero metrics). The failure is the opposite one: a cold engineer console with one colour (amber) carrying four meanings |
| | **Total** | **11/20** | **Acceptable: significant work needed** |

**Anti-patterns verdict: pass, but cold.** Nobody would say "AI made this". They would say "an engineer made this for themselves". The honesty is real (every count reconciles, every check is server data), and the surface hides it behind identifiers, raw signal strings and alarm colours.

### 1.2 Findings, ranked

Severity: P0 blocks the task, P1 a first-time user stalls or is misled, P2 friction or coldness, P3 polish. Each finding says which of the three owner concerns it hits: **stall** (first-time user does not know what to do), **cold** (feels like a console), **trust** (evidence exists but is hidden or misread).

**[P1] F1. A passing check is shown as a red "critical" alarm.** *trust*
Verify › Why this needs you (`WhyList`). "cleanup changed content 1.00 `critical`" renders with a red chip while its detail says "passed". "Critical" means "this signal can hold a block on its own", not "this failed", but a reviewer reads red as failure. The one check that proves cleanup did not alter the text looks like the problem.
Fix: split the list into *what held this block* and *checks that passed* (with a tick and text). Never colour a passed check as a problem. `clarify`, `colorize`.

**[P1] F2. Queue cards are titled by truncated identifiers and are indistinguishable.** *stall, cold*
`QueueCard.tsx`. Line 1 is `b-sc… p.9 paragraph score 0.12 · below 0.85`. At 288px every id truncates to "b-sc…", and the top 12 cards all carry the same three chips. A first-time user cannot tell what any card is about or why one differs from the next.
Fix: human title first (section heading + page), a one-line excerpt of the text, then reasons with the specific word, then the id in small mono (§2.8.3). `clarify`, `layout`.

**[P1] F3. Reason chips are jargon, and identical chips stop carrying information.** *stall, cold*
"parsers disagree", "weak OCR word", "low OCR", "numeric spec". Hover hints exist (`signalHint`), but the chip itself must make sense without hovering (principle 8). The distinguishing fact ("weakest word is 4471-A", "across", "N-m") is on the server and never reaches the card.
Fix: rewrite table in §2.8.2; carry the weakest word onto the card.

**[P1] F4. The strongest evidence is a log line.** *trust*
"ocr vs ocr_alt 0.125; numeric: '+ 0.05 using a feeler gauge' vs ''; 'replace the control board with genuine part p / n 4471' vs 'i e'…". The two readings side by side are the best reason to trust (or distrust) a block, and they are printed as a lower-cased debug string. The scale note ("Each signal runs from 0 to 1; 1.00 means that check found nothing wrong") is needed only because values lead.
Fix: show both readings as two labelled lines in the manual's typeface; put the number after the sentence.

**[P1] F5. The page is too small to verify against, so the core act needs a keypress.** *trust, stall*
Source pane is 400px wide at 1440: the outlined block's text is about 5px tall. On the demo's first block the page reads "±0.05" and the extracted text reads "+0.05"; that difference is invisible without pressing `Z`. Verification is comparing text with the page; the page has to be legible by default.
Fix: a magnified strip of the page cropped to the block (at least 1.3x, pannable when lines are long), with the whole page as a small locator next to it (§2.5).

**[P1] F6. The figure rail is effectively invisible.** *trust, stall*
At 1440 the figure rail renders at y = 13,971px, below the 216-card queue in document flow. SPEC §7.2 makes it one of the four panes; in practice nobody will find it.
Fix: panes scroll independently inside a fixed-height work area; the rail sits in view (§2.5).

**[P1] F7. No arrival moment and no map of the journey.** *stall*
First load drops the user into three dense columns plus a prose guide. Nothing says "your 3 manuals were read: 32 pages, 364 blocks, 20 figures" or "here are the four steps and where you are". The step tabs exist but carry no description of what each step is for.
Fix: an inline welcome (not a modal or carousel) and a step map with a one-line purpose and a live count per step (§2.8.4).

**[P1] F8. 200% zoom breaks the decision surface.** *stall* (accessibility)
At 720 CSS px the layout stacks and the queue alone is ~13,800px tall; text and page are never visible together. PRODUCT.md requires "works at 200% zoom".
Fix: below 1100px wide, Verify switches to a two-region layout (queue collapses to a "Block 3 of 216" header with prev/next; text and page strip stack) (§2.5). `adapt`.

**[P2] F9. Progress is a row of raw counts; "locked" frames the user as behind.** *cold*
"Queued 216 Auto-approved 148 Flagged 0 Done 0 In scope 364" and an amber "locked: 216 to review" from the first second. There is no sense of distance covered.
Fix: a reconciling progress bar (auto-approved + done by you + flagged + to review = in scope), "0 of 216 reviewed by you", quiet milestone acknowledgements (§2.8.5). Export's step label says "after your review" until review is under way.

**[P2] F10. The guide column costs 24% of the width and repeats itself.** *cold, stall*
The 350px "Getting started" column holds paragraphs with inline keycaps; Help › Guide repeats the same text; a third line says "Press ? for the guide". Three places, same prose, competing with the work.
Fix: replace with one "next step" line or card that changes with state (§2.3); keep Help for the full text.

**[P2] F11. Amber means four different things.** *cold, trust*
"mock models", "locked", "Low cohesion", "Scanned: OCR text" all use the same amber; red is used for "critical" on nearly every card. Colour has stopped meaning anything, and red has become wallpaper.
Fix: a semantic token set where each hue has one job (§2.3), red reserved for failed checks only.

**[P2] F12. Scope rows are ambiguous for a first-timer.** *stall*
"General Precautions" appears three times in clean.pdf (and three times in scanned.pdf), "Belt Inspection", "Coolant Service" and "Fuse Replacement" twice each; the page ranges that tell them apart are truncated. "Low cohesion" is a statistics word.
Fix: page range beside duplicate titles; "Mixed subjects" with a one-line hint (§2.8.2).

**[P2] F13. The Agent screen is text describing an empty room.** *cold, stall*
Three headings, each "0", with paragraphs explaining what would appear. No picture of a proposal, no sense of how flags get here, calibration in statistics language ("edit rates by score bucket", "Target edit rate 2%").
Fix: a real three-part workspace with designed empty states (§2.5.4).

**[P2] F14. Export lists 20 raw ids and offers the override first.** *trust, cold*
Blockers are `b-clean-p002-04` chips ("first 20 listed by the server"); the "Export anyway" form is open below them. The path of least resistance is the override.
Fix: blockers grouped by article with human titles and counts; the override behind a disclosure that states its consequence (§2.5.5).

**[P3] F15. Flat typography; one size does everything.** *cold*
14px for UI, data, prose and the manual's text alike; headings 16 to 18px. The manual's words and the app's words look the same.
Fix: a distinct reading face for the manual's text (both directions do this, differently) and a 1.2 scale for UI. `typeset`.

**[P3] F16. Models table and hardware probe are first-run noise.** *stall*
Seven rows of `mock/mock-1` and "Run hardware probe" sit beside the primary decision on Scope.
Fix: collapse to "Models and hardware" with a one-line state ("Demo placeholders"), expanded on demand (`M` still focuses it).

### 1.3 Systemic patterns

- **Identifier first, meaning second** (cards, Export blockers, extracted pane title). The fix is one rule, not many patches: a human title before an identifier everywhere a block is named (principle 8).
- **Number first, sentence second** (scores, signal values, "0 to 1" scale explainer). Rule: sentence, then the number as supporting evidence.
- **No token layer.** Raw Tailwind palette classes across components make any re-skin a find-and-replace. Introduce semantic tokens before restyling anything.
- **Explanation lives in prose blocks** (guide column, Help, Agent) rather than at the control. Principle 4 says explanations live where the decision is.

### 1.4 What is working (keep it)

- Every count reconciles on screen and the server is the source of each term (`reconcile-review`, per-document parse lines). This is the product's best trust feature; the redesign keeps every equation, it only adds a human sentence in front.
- Numbers are bolded in the extracted text; numeric blocks are always queued, and the card says so.
- "Why this needs you" sits at the decision, and checks that did not run say so instead of showing as passed.
- Keyboard flow is complete and shown as keycaps on the action bar; focus rings are visible; "Saved" confirms autosave.
- Unassigned blocks are a visible catch-all ("Listed here, never dropped").

### 1.5 Recommended Impeccable passes (in order)

1. **[P1] `clarify`**: the copy rewrites in §2.8 (chips, why list, cards, Scope lines, Export blockers).
2. **[P1] `layout`**: Verify work area with independent pane scroll, magnified page strip, figure rail in view.
3. **[P1] `onboard`**: welcome moment, step map with next action, Agent and Export empty states.
4. **[P1] `adapt`**: Verify below 1100px wide (200% zoom).
5. **[P2] `extract` then `colorize`**: semantic token layer, then the chosen direction's palette.
6. **[P3] `typeset`**: reading face for the manual's text, UI scale.
7. `polish` last.

---

## 2. Shape brief

### 2.1 Feature summary

A craft pass over all four screens of Manual Labor that keeps every behaviour and every piece of evidence, and changes how the app greets, guides and explains. It is for a technician or documentation owner reviewing manuals for about an hour at a desk, often for the first time, who is accountable if a torque value is wrong. It has to make the next action obvious, make the evidence legible without hovering or zooming, and feel like a calm colleague rather than a console.

### 2.2 Primary user action

**Decide on the current block by comparing its text with the page** (Verify: `A` / `E` / `F`). Everything else (Scope, Agent, Export) exists to get the right blocks in front of that decision or to finish after it. The design is judged by how quickly and confidently a first-time user makes their first ten decisions.

### 2.3 Design direction

**Scene sentence.** A maintenance technician or documentation owner at a desk in a bright plant office in daytime, the paper manual or its PDF open beside them, working through a review queue for an hour with steady attention and a little anxiety, because their name is on the torque values. → **Light theme**, warm paper neutrals, high legibility; no dark mode in scope.

**Colour strategy.** Product register, Restrained as the floor. Direction A goes to a small **Full palette** (four named roles, each with one job); Direction B stays **Restrained** (tinted stone neutrals plus one ember accent at under 10% of the surface). Both obey: one meaning per hue, red only for a failed check, never colour alone (every state also has an icon or a word).

| Role | A "Warm workbench" | B "Calm guide" |
|---|---|---|
| Surface | birch paper `oklch(0.972 0.014 82)`, raised `oklch(0.992 0.006 85)` | stone paper `oklch(0.985 0.003 85)`, rail `oklch(0.962 0.006 85)` |
| Ink / muted | `oklch(0.27 0.025 55)` / `oklch(0.47 0.025 60)` | `oklch(0.25 0.012 70)` / `oklch(0.48 0.012 70)` |
| Primary action, current step | terracotta `oklch(0.55 0.14 38)` | ember `oklch(0.52 0.13 48)` (the only accent) |
| Needs you | marigold wash `oklch(0.93 0.07 88)` with ochre ink | ember outline and wash |
| Done / cleared | sage `oklch(0.93 0.035 150)` / `oklch(0.38 0.07 150)` | ink with a tick (no extra hue) |
| Failed check | brick `oklch(0.50 0.16 25)` + ✕ | the same |
| Focus ring | blue `oklch(0.50 0.16 255)`, 2px, both directions (distinct from every state colour) | |

**Typography.**
- A: Figtree for UI (15px base, 1.2 scale), **Atkinson Hyperlegible** for the manual's text and excerpts (designed to separate 0/O, 1/l/I, so a part number like "4471-A" or "0.05" is unambiguous), IBM Plex Mono for ids.
- B: Instrument Sans for UI (14.5px base), **Source Serif 4** for the manual's text (the manual's words are set in a serif, the app's words in a sans, so the user always knows which voice they are reading), IBM Plex Mono for ids.

**Named anchors.**
- A: *Things 3* (warm, unhurried task flow with quiet completion), *a Muji paper notebook* (warm off-white, ink, restraint without coldness), *Stripe's onboarding checklist* (progress you can see, one next step).
- B: *Linear's sidebar* (persistent place-keeping, calm density), *Readwise Reader* (serif reading surface beside sans chrome), *a printed aircraft maintenance task card* (step, check, sign-off; the step is the unit of trust).

**Category reflex check.** First order: "industrial equipment tool" suggests safety yellow and black, or navy enterprise. Neither direction uses them. Second order: "friendly tool that is not a console" suggests SaaS cream with a purple gradient; both avoid gradients, and A's warmth comes from roles (terracotta = act, sage = cleared, marigold = needs you), not decoration.

### 2.4 Scope

- Fidelity: this brief and the mocks are mid-fi direction artifacts. The build target is production-ready.
- Breadth: the whole surface (shell, welcome, Scope, Verify, Agent, Export, Help). Mocks cover Scope and Verify only.
- Interactivity: no behaviour changes; copy, layout, tokens, typography, and one additive server field.
- Time intent: polish until it ships, in the order of §1.5.

### 2.5 Layout strategy

**2.5.1 Shell.** The four steps are the navigation and the progress model at once. Each step shows its name, a one-line purpose, and a live count or state ("Scope · 364 blocks in", "Verify · 216 to review", "Agent · nothing flagged yet", "Export · after your review"). A: horizontal step bar in the header. B: vertical step rail on the left (248px), with a "Your next step" card at the top that changes with state and carries the primary action. The demo-models notice moves from an amber pill to a calm note (A: pill in header; B: rail footer).

**2.5.2 Welcome (first run).** Inline, dismissible, never modal, shown once per project (the existing server-side `ui/guide` flag). It states what was read (3 manuals, 32 pages, 364 blocks, 20 figures, all real counts), what the user controls, and the four steps with one line each. One primary button ("Start with step 1") and one quiet escape ("I have used this before"). A gives it a full-width warm band; B a single line, because the rail already maps the journey.

**2.5.3 Scope.** Sources (with the OCR note in plain words) / topic list with per-document reconcile line / "What you will get" receipt with the estimated review explained as a sentence and the primary action. Duplicate topic titles show their page range next to the title. Models and hardware collapse to one line. The 350px guide column is gone; its content moves to the next-step card (B) or the welcome and inline sub-lines (A), and to Help.

**2.5.4 Verify.** A fixed-height work area under the status row; every pane scrolls on its own (fixes F6, F8 and the 14,000px document).
- A (side by side): queue 320 | text + "Why this needs you" 440 | page column (magnified strip at full column width, then the whole page as a locator and the figure rail beside it). A one-line **coach** under the progress bar says what to look at for this block, built only from this block's signals ("The two readings differ on its second line, and the scanner was least sure of '4471-A'").
- B (read down): queue 292 | work area: a full-width **page band** at the top (the magnified strip at about 1.4x plus a page locator), then the extracted text directly under it, then evidence cards and the figure rail on the right. The eye moves straight down from the page line to the extracted line; on the demo's first block "±0.05" on the page sits directly above "+0.05" in the text.
- Both: the action bar stays fixed; Approve is the one primary button and says what it records ("and mark its numbers checked" on numeric blocks).
- Below 1100px wide (200% zoom): the queue collapses to a header ("Block 1 of 216", prev/next, open-queue button); text and page strip stack; the figure rail becomes a disclosure under the text.

**2.5.5 Agent (a real workspace).** Three parts, each with a designed empty state:
1. *Open flags* (left list): human title, flag category, your note, page. Empty: "Nothing flagged. Flags are for blocks you would rather not fix by hand. In Verify, press F on a block to send it here." with a link back to Verify showing its live count.
2. *Proposal* (centre): before/after in the manual's typeface with the diff, then "Checks run again" as rows with pass or fail (icon + word), then the model's rationale with each quote marked found or struck through. Accept only when every re-check passed; Edit; Reject with a reason (the item returns to the list with its history). Header: "Run agent pass on N open flags" (background job with progress; review stays usable) and "Accept all passing (n)".
3. *Calibration* (right): "How your decisions compare with the scores": one row per score range with decisions, edits and edit rate. Empty: "Builds as you review. After 20 decisions in a score range you will see how often you edited blocks there, and a suggested threshold. It is never applied for you."

**2.5.6 Export.** Locked state: "216 blocks are still to review" with blockers grouped by article ("Coolant Service · 9 to review", each opening Verify filtered to it), the raw ids available under each group. Override behind a disclosure, "Export before review is finished", that states its consequence before the form. Unlocked: one summary (articles, figures, pages covered, review stats), the download, and the SHA-256 to compare.

### 2.6 Key states

| State | What the user sees and should feel |
|---|---|
| First run | Welcome with real counts; the step map; one obvious first action. Oriented, not lectured |
| Parsing / scoring in progress | Step shows "Preparing scanned.pdf (page 4 of 12)"; Verify queue usable for docs that are ready; doc chip keeps "still preparing" (asserted) |
| Mid-review | Progress bar moves with each decision; "N of 216 reviewed by you"; coach line per block |
| Quiet milestone | When a document or an article has nothing left to review: one line, e.g. "Coolant Service is fully reviewed." Shown 4s and kept in the step's sub-line. No animation beyond a 200ms fade |
| Queue empty | Verify becomes a summary: "All 216 reviewed. Approved X, edited Y, flagged Z." Next step points to Agent if flags are open, else Export |
| Flags open | Agent step shows "N to fix"; Export sub-line "after N flags are resolved" |
| Failed check | Brick red with ✕ and the check's sentence, only here |
| Stale / re-scoring | "changed since approval" and "re-scoring" kept verbatim (asserted) |
| Error (API) | Inline, at the pane that failed, with retry; never a toast-only error |
| Demo models | One calm note; never amber alarm styling |
| Scanned source | Plain-language note that includes the server's OCR warning string verbatim |
| Long titles / ids | Titles wrap to two lines on cards; ids never truncate (they are short once they are not the title) |

### 2.7 Interaction model

Unchanged: every binding in `HOTKEYS` and `LOCAL_KEYS`, the zone and modal scoping, and 12 §4 in full. Specifically:
- No new `focus()` calls. The next-step card (B) and coach line (A) are outside every `data-zone`, carry no `aria-modal`, and register no keys.
- The welcome band is a region, not a dialog; dismissing it returns focus to where it was only if focus was inside it (the same rule as Hide guide).
- `?` still opens Help with Guide / Keyboard shortcuts / Glossary; the guide text moves there in full.
- Keycaps sit next to the action they trigger (action bar, next-step card), never inside paragraphs.
- Motion: 150 to 200ms ease-out-quart for state changes (card selection, progress bar width via `transform: scaleX`, milestone fade). `prefers-reduced-motion` removes all of it. No confetti, no celebratory animation.

### 2.8 Content requirements

#### 2.8.1 Voice rules

1. Say what a person would say first; the signal name and number follow as secondary text.
2. Name the specific thing (the word, the line, the number), not the category.
3. Say what will happen before it happens ("Approve, and mark its numbers checked").
4. Acknowledge facts, never praise: "Coolant Service is fully reviewed", not "Great job!".
5. "We" only for the app's own actions (reading, checking); never for certainty claims.
6. Identifiers are secondary, never removed: mono, smaller, selectable, still carrying their test ids.
7. Sentence case, numerals, units exactly as in the manual, no em dashes.
8. A count on screen is always the server's count; a sentence never rounds or estimates it.

#### 2.8.2 Rewrites of the current jargon

| Where | Current | Proposed |
|---|---|---|
| Reason chip | parsers disagree | Two readings differ |
| Reason chip | text layer ≠ OCR | PDF text and scan differ |
| Reason chip | weak OCR word | Unsure word "4471-A" (the actual word) |
| Reason chip | low OCR | Faint scan |
| Reason chip | reading order | May be out of order |
| Reason chip | table shape | Table rows or columns do not line up |
| Reason chip | garbled text | Garbled characters |
| Reason chip | cleanup changed content | Cleanup changed words (fail) / Cleanup kept every word (pass) |
| Reason chip | figure crop | Figure cut from the page image |
| Reason chip | low-res figure | Low-resolution figure |
| Reason chip | weak figure match | Unsure this figure belongs here |
| Reason chip | verifier disagrees | A second model reads it differently |
| Reason chip | numeric spec | Has numbers |
| Why list tag | `critical` (red) | removed; list split into "What held this block" and "Checks that passed" |
| Why list detail | ocr vs ocr_alt 0.125; numeric: '+ 0.05 using…' vs '' | "The two readings differ" + Reading 1 / Reading 2 as lines + "agreement 0.13 of 1" |
| Why list detail | min 0.899 at '4471-A'; 68 words | "Least certain word: '4471-A'" + "0.90, lowest of 68 words" |
| Why rule | Rule: always reviewed (numeric spec). Blocks with numbers are always reviewed… | "Has numbers, so a person always checks it. 0.25 mm · P/N 4471-A. Approving records these numbers as checked by you." |
| Card score | score 0.12 · below 0.85 | score 0.12 · needs 0.85 (secondary line) |
| Status strip | Queued 216 | 216 to review (A: "waiting for you") |
| Status strip | Auto-approved 148 | 148 auto-approved (A adds "cleared by the checks" in the legend) |
| Sort option | Worst first | Most doubtful first (value `worst_first` unchanged) |
| Scope chip | Low cohesion | Mixed subjects (hint: "These blocks cover different subjects. Check them in Document structure.") |
| Source kind | born digital pdf / scanned pdf | Text PDF / Scanned PDF |
| OCR warning | OCR: 12 page(s) without a text layer; OCR text is less reliable | "Read from scans." + the server string verbatim + "so more of this manual will come to you to check." |
| Doc reconcile | 150 parsed = 22 headers and footers (excluded) + 127 in topics + 1 unassigned | 150 blocks found: 127 in topics, 1 not placed in a topic, 22 page headers and footers left out (A) / "150 blocks found = 127 in topics + 1 not placed + 22 page headers and footers, left out" (B) |
| Summary | Estimated review: 216 blocks (207 with numeric specs) under threshold 0.85 | "Estimated review: 216 blocks. 207 contain numbers, which a person always checks; the other 9 scored under 0.85." |
| Agent calibration | How often you edited blocks at each confidence level, from 0 decisions. Target edit rate 2% | "How your decisions compare with the scores" + the empty state in §2.5.5 |
| Export blockers | b-clean-p002-04 … (first 20 listed by the server) | Grouped by article with counts; ids under each group |
| Nav sub-line | locked: 216 to review | Export · after your review (before any decision) / locked: 216 to review (once review has started) |

The 9 in "the other 9" is `review_load.queued − review_load.numeric_queued` from `/api/scope/summary`, not an estimate.

#### 2.8.3 Queue card anatomy (both directions)

```
┌──────────────────────────────────────────────────┐
│ 4.1 Coolant Service                         p. 9 │  human title: enclosing section heading + page
│ Do not operate the unit while the cover plate…   │  first line of clean_text, manual's typeface
│ Two readings differ · Unsure word "4471-A" ·     │  reasons in words, the specific word named
│ Has numbers                                      │
│ b-scanned-p009-10            score 0.12 · needs 0.85 │  id (mono, data-testid stays), score as support
└──────────────────────────────────────────────────┘
```
The title is deterministic: the nearest structure-view section heading containing the block (falls back to the document title, then to "Page 9, paragraph"). No model writes a card title. **Contract addition needed**: `QueueItem` gains `section_title: str | null`, `excerpt: str` (first 120 chars of `clean_text`, or `raw_text` before cleanup) and `weakest_word: str | null` (from the `ocr_min` signal). Generated types regenerate as usual. Card height grows from 64px to about 104px (about 8 visible at 1440 instead of 12); the trade is distinguishability for density.

#### 2.8.4 Welcome copy (A wording; B uses the first two sentences)

> **Welcome. Your 3 manuals are read and ready.**
> We found 364 blocks of text (paragraphs, lists and tables) and 20 figures across 32 pages. You decide what goes into the knowledge base. Anything the checks cannot vouch for comes to you, next to the page it came from.
> 1 Choose what goes in. 2 Check 216 blocks against the page. 3 Fix anything you flag. 4 Export the reviewed knowledge base.
> [Start with step 1] [I have used this before]

#### 2.8.5 Progress model

- **Journey**: the four steps with live state (§2.5.1). A step is "done" only when its server condition holds (scope confirmed; queue at 0; open flags at 0; export produced).
- **Review**: one reconciling bar, segments in server terms: auto-approved + done by you + flagged + rejected + to review = in scope. Text: "N of 216 reviewed by you". The equation line (`reconcile-review`) stays under it, verbatim.
- **Milestones**: per document and per article reaching zero to review; one quiet line each.
- **Time left**: not shown by default. If the owner wants it (§7, D5), only after 20 decisions in this session, computed from real decision timestamps, phrased "about 40 minutes at your pace so far".

### 2.9 Recommended references (Impeccable)

`clarify.md` and `ux-writing.md` (§2.8), `layout.md` and `spatial-design.md` (Verify work area), `onboard.md` (welcome, empty states), `adapt.md` (200% zoom), `colorize.md` and `color-and-contrast.md` (token roles, AA on every wash), `typeset.md` and `typography.md` (reading face), `interaction-design.md` (focus, keycaps), `motion-design.md` (reduced motion), `cognitive-load.md` (one next step).

### 2.10 Open questions for the implementer

1. Magnified strip: crop from the existing page PNG at render scale, or request a higher-DPI crop endpoint (`/api/docs/{slug}/pages/{page}/crop?bbox=`)? The demo's 1275px page render gives about 1.4x; long lines may need horizontal pan.
2. Coach line (A) and next-step text (B): a pure function of the block's `why` list; it must say nothing that the signals do not say. Needs its own unit tests next to `reasons.test.ts`.
3. Token layer: Tailwind `theme.extend.colors` mapped to CSS custom properties in OKLCH, so both directions are a variable swap.
4. Fonts: self-host (local tool, offline use) rather than Google Fonts at runtime.

---

## 3. Mocks

Two static HTML pages, each showing Scope (first run) and Verify (first block) at 1440px with the demo project's real content (same counts, same block text, same reasons, the real page 9 render):

- Direction A, Warm workbench: `/private/tmp/claude-501/-Users-ashwinchidambaram-dev-projects-doc-to-KB/a0f62346-3931-445f-9ba7-d1a960acc5e6/scratchpad/mocks/A.html`
- Direction B, Calm guide: `/private/tmp/claude-501/-Users-ashwinchidambaram-dev-projects-doc-to-KB/a0f62346-3931-445f-9ba7-d1a960acc5e6/scratchpad/mocks/B.html`

Everything shown is server data except the three proposed fields of §2.8.3 (section title, excerpt, weakest word), which are taken from `/api/verify/blocks/{id}` and the structure groups. They are direction artifacts, not implementation.

---

## 4. Recommendation

Build **B, Calm guide**, and carry three things over from A. B answers the owner's four words structurally rather than decoratively: the always-visible rail with "Your next step" *guides* (it replaces three copies of the guide prose with one sentence that changes with state), the read-down page band puts the page line directly above the extracted line so *trust* comes from seeing (on the demo's first block "±0.05" sits right above "+0.05"), and the serif-for-the-manual / sans-for-the-app split tells a first-timer at a glance which words are the source and which are the tool. Its restraint suits someone who is accountable for a torque value, and a single ember accent keeps "your next move" unambiguous. A is warmer, but its four-role palette is easier to overspend as more states arrive. From A, take: the sage/marigold status washes (B's ink-only "done" reads too cold at the milestone moments), the Atkinson Hyperlegible reading face for excerpts and ids-adjacent numbers if the owner finds Source Serif's figures too literary for part numbers (D3), and the coach line wording as the text of B's next-step card.

---

## 5. Test ids and control names the redesign would change

All `data-testid` values survive unchanged (`card-*`, `queue-score`, `block-id`, `cnt-*`, `reconcile-review`, `why-rule`, `check-faithfulness`, `figure-rail`, `rail-*`, `view-*`, `selection-summary`, `low-cohesion`, `ocr-warning`, `scanned-badge`, `source-chip`, `coverage-chip`, `confirm`, `step-short-*`, `guide-progress`, `export-locked`, `blocker-link`, `agent-*`, `override-*`, …). Regions, toolbar, listbox, radio and dialog names survive ("Source page", "Extracted text", "Review queue", "Review actions", "Suggested topics", "Document structure", /per document/, "Help", "Flag block", "Attach a figure", "Sort", "Edit block text", "Also review auto-approved blocks below", "Why this needs you, signals", "Figures in this article", "Original vs cleaned", "Confirm content change"). Copy kept verbatim because it is asserted: "Saved", "Ready", "here", "Catch-all", "Unassigned blocks", "changed since approval", "still preparing", "numbers verified", "human", "Why this needs you", "Estimated review", "Export is locked", "Only blocks under the X threshold" / "Showing N auto-approved blocks below X", "In scope … = … to review + … auto-approved + … done + … flagged + … rejected", "N to review" / "locked: N to review", the server OCR warning string.

Proposed changes (each needs the named spec updated in the same commit):

| Change | Assertion affected |
|---|---|
| "Low cohesion" → "Mixed subjects"; aria-label "Low cohesion 0.10" → "Mixed subjects, cohesion 0.10" | `e2e/scope.spec.ts:162-163` |
| Per-document reconcile line rewording | `e2e/onboarding.spec.ts:207`, `e2e/ux-onboarding.spec.ts:77` (regex) |
| Guide column replaced by step rail / next-step card: buttons "Next", "Previous", "Hide guide" and the "Step 1 of 4" progress text leave the panel (Help › Guide keeps paging) | `e2e/onboarding.spec.ts:66,104-106`, `e2e/ux-onboarding.spec.ts:50,185,272,400,402` |
| Guide text "Estimated review is how many selected blocks will need a person" moves to Help and the summary sentence | `e2e/ux-onboarding.spec.ts:59` |
| `complementary` "Getting started": kept as the rail's name in B; removed in A | `getByRole("complementary", { name: "Getting started" })` (2 uses), A only |
| Export step sub-line reads "after your review" until the first decision; accessible description /Step 4 of 4\. Locked: / kept once review starts | `e2e/onboarding.spec.ts:174-176` (seeded projects already have decisions or need the description kept; recommend keeping the description text unchanged and changing only the visible sub-line) |
| Sort option label "Worst first" → "Most doubtful first" (value unchanged) | none found (tests assert the value `worst_first`) |
| Confirm button: name kept "Confirm scope and go to Verify" | none |

---

## 6. Impact and follow-ups

- **Affected surfaces**: shell, Scope, Verify, Agent, Export, Help, onboarding copy (`guide.ts`, `hints.ts`, `glossary.ts`, `userGuide.ts`, `docs/USER_GUIDE.md`), `verify/labels.ts`, `reasons.ts`, `WhyList`, `QueueCard`, `StatusStrip`, Scope rows and summary.
- **Contract change**: three additive `QueueItem` fields (§2.8.3); regenerate schemas and frontend types; add unit tests for the section-title fallback chain.
- **Drift risk**: the reason rewrites must stay a single map (`SIGNAL_LABEL`) plus one sentence builder; no component writes its own reason copy. Status colours come only from tokens.
- **Deferred**: dark theme (not justified by the scene); the flag dialog and crop editor restyle (follow the tokens, no layout change); Help dialog layout.
- **Gate for this module** (proposed): all existing unit and e2e tests green after the §5 updates; a new Playwright pass at 720px viewport proving text and page strip are co-visible on Verify; contrast check of every token pair at AA; UX check subagent runs the first 20 decisions keyboard-only on both the clean and scanned fixtures.

---

## 7. Decisions for the owner

Answer these and the brief is confirmed.

- **D1. Direction.** A (Warm workbench), B (Calm guide), or B with A's status washes (recommended)?
- **D2. Verify layout.** Page side by side with the text (A), or the page band directly above the text (B, recommended)?
- **D3. Reading face for the manual's text.** Serif (Source Serif 4: "this is the manual speaking") or hyperlegible sans (Atkinson Hyperlegible: strongest 0/O and 1/l/I separation for part numbers)?
- **D4. Human card titles.** Approve the additive `QueueItem` fields `section_title`, `excerpt`, `weakest_word` (server change, deterministic, no model involved)? Without them, cards can only show the page and the generic reason.
- **D5. Time left.** Never show it (recommended), or show it after 20 decisions, computed from your real pace?
- **D6. Welcome.** Full welcome band on first run (A) or one line plus the rail (B)?
- **D7. Test changes.** Accept the copy and guide-panel assertion changes in §5 (two renamed strings, the guide panel's Next/Previous/Hide controls moving into Help)?
- **D8. Fonts.** Self-host the chosen fonts for offline use (recommended), or allow Google Fonts at runtime?

## 7. Owner decisions (confirmed 2026-10-30)

- D1 Direction: **B "Calm guide" with A's warmth**: B's step rail, "Your next step" card and page-above-text Verify layout; A's sage/marigold/terracotta status colours, the progress bar that adds up to in-scope, and A's welcome band.
- D1a (owner, 2026-10-30): keep A's Verify progress bar exactly as mocked: a segmented bar over the whole in-scope total with "N of M checked by you", "cleared by the checks", "waiting for you", "flagged", each segment a status colour, with the reconciliation line beneath it.
- D2 Page placement on Verify: directly above the extracted text (B), magnified to the block, with the whole page one key away (Z).
- D3 Reading face for the manual's text: **Atkinson Hyperlegible**; the app's own words in the regular sans.
- D4 Server change approved: queue items gain `section_title`, `excerpt`, `weakest_word`, computed by deterministic rules, no model involved.
- D5 Never show "time left".
- D6 First run: the full welcome band (names the manuals and the four steps; "Start with step 1" / "I have used this before"), once per project; the rail stays after.
- D7 Test assertion changes listed in §5 accepted; test ids survive where the brief says they do.
- D8 Fonts bundled locally (offline product, SPEC AC8); no runtime Google Fonts.
- Shape gate: the owner approved this brief in a separate response ("B + A's warmth", server fields, Atkinson Hyperlegible, full welcome band). Image step skipped: no native image generation in this harness; the HTML mocks are the north star.

## 8. Build notes (2026-10-30, recorded by the owner's agent after inspecting the build)

What was built: commit 474e06b (craft) on top of ee6c9ed (server fields). Screens inspected live at 1440, 1024 and 720 wide and at 720x450 (200 percent zoom); screenshots in the session scratchpad.

Deviations from §2, each with the reason:

- **Queue reason labels keep their old words** ("parsers disagree", "weak OCR word", "numeric spec"): `ux-verify.spec.ts` T3 asserts them and T3 is not in §5. The card now names the uncertain word next to the label, which is the translation §2.8 asked for.
- **The scorer's raw detail string stays visible** as a muted secondary line under each readable check: T5 reads each list item's `innerText` and asserts the detail verbatim, so a collapsed disclosure would fail. The readable sentence is primary; the raw line is last and small.
- **The override form and the Models panel stay expanded**: tests focus controls inside them.
- **The Export step reads "locked: N to review" before the first decision**: §5 keeps that string, and the export status carries no decision count to switch on.
- **Quiet milestones (§2.8.5) are not built**: a per-document "fully reviewed" line needs a per-document queued count in `/api/verify/queue` `docs[]` (today: state, stale, waiting_for) and a per-article one needs article counts; both are additive server fields and are left as a follow-up. The empty-queue state keeps its reconciled counts line and the next-step link.
- **One focus call added**: "Start with step 1" in the welcome band moves focus into the group list. This amends design 12 §4 rule 1 (focus calls only for Help and Hide): a button whose whole purpose is "go to step 1" may move focus when the person presses it. "I have used this before" behaves as Hide did. Nothing moves focus on its own.
- **Bundle**: 496 kB of JavaScript (Vite warns above 500 kB); Atkinson Hyperlegible adds 72 kB of woff2, bundled under `frontend/src/assets` with its SIL OFL licence.

Defect found during the build's e2e runs and fixed at the cause (edd799c): the page strip and the source pane fetch the same page PNG together, and `render_page_png` wrote both renders to one `<out>.tmp`, so the second `os.replace` raised `FileNotFoundError`. Each call now writes its own temp file; `tests/parse/test_render_race.py` reproduced it 5 of 6 runs before the fix.

The craft build's "approves did not advance" observation (UX2, T13) did not reproduce: UX2 passed 3 of 3 alone and T13 passed with focus landing in 6 to 18 ms, both with the machine at load 13 to 17 from an unrelated render. The earlier failures were 5 s expect timeouts under load 7 to 12, the same tests that failed in module 12's loaded run.
