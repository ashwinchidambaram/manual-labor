---
name: Manual Labor
description: A calm, guided review tool that turns equipment manuals into a faithful, reviewed knowledge base.
colors:
  paper: "#fbfaf7"
  raised: "#fffefb"
  rail: "#f5f2ed"
  sunk: "#f8f5f1"
  line: "#d9d3cc"
  line-soft: "#e9e6e0"
  line-strong: "#867f77"
  ink: "#27201a"
  muted: "#625952"
  page: "#fefdfc"
  act: "#ad4828"
  act-hover: "#953a1c"
  on-act: "#fefcf7"
  act-wash: "#ffe9de"
  act-line: "#e4a78f"
  act-ink: "#983d1f"
  needs-wash: "#fce8b8"
  needs-fill: "#eec05b"
  needs-line: "#d9a850"
  needs-ink: "#6c4302"
  done-wash: "#daf1dd"
  done-mid: "#62946c"
  done-ink: "#295233"
  fail: "#ac3031"
  fail-wash: "#ffe7e4"
  fail-line: "#e6a49e"
  focus: "#0961bb"
typography:
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  heading:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.07em"
  manual:
    fontFamily: "Atkinson Hyperlegible, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.7
  id:
    fontFamily: "ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.act}"
    textColor: "{colors.on-act}"
    rounded: "{rounded.lg}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.act-hover}"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "0 14px"
    height: "44px"
  chip-waiting:
    backgroundColor: "{colors.needs-wash}"
    textColor: "{colors.needs-ink}"
    rounded: "{rounded.pill}"
  chip-cleared:
    backgroundColor: "{colors.done-wash}"
    textColor: "{colors.done-ink}"
    rounded: "{rounded.pill}"
  chip-failed:
    backgroundColor: "{colors.fail-wash}"
    textColor: "{colors.fail}"
    rounded: "{rounded.pill}"
  queue-card-current:
    backgroundColor: "{colors.act-wash}"
    textColor: "{colors.ink}"
  next-step-card:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "14px"
---

# Design System: Manual Labor

## 1. Overview

**Creative North Star: "The Calm Guide"**

A knowledgeable colleague at the next desk, walking a technician through a printed maintenance task card: one step at a time, the evidence on the table, nothing hidden. The surface is warm stone paper under daylight, quiet enough for an hour of steady attention, and exact wherever a torque value or a part number is at stake. Warmth comes from roles, not decoration: terracotta means "your move", marigold means "waiting for you", sage means "cleared". The manual's own words are always set in a second, hyperlegible face, so the reader can tell at a glance which words are the source and which are the tool.

The layout is a journey, not a dashboard. A step rail on the left (a bottom sheet below 1100px) always shows the four steps and one "Your next step" sentence built from real state. Verify reads straight down: the page, magnified to the block, sits directly above the extracted text, with the evidence beside it. Every count on screen is a server count and every total reconciles on screen.

This system rejects what PRODUCT.md names: consumer onboarding carousels and confetti; AI products that show a single "confidence" number with no reason; dark "hacker" dashboards; marketing gradients.

**Key Characteristics:**
- Light theme only: warm stone neutrals tinted toward the terracotta hue, never pure white or black.
- Four status hues, one meaning each, always paired with a word or icon.
- Two voices in type: the app's system sans, the manual's Atkinson Hyperlegible.
- A sentence before a score; a human title before an identifier; identifiers kept, smaller, in mono.
- Fixed-height Verify frame on wide screens with independently scrolling panes; flowing pages everywhere else.

## 2. Colors

A restrained warm-paper base carrying a small full palette of four status roles, each with exactly one job. Canonical values are OKLCH (in `frontend/src/index.css` comments); tokens are shipped as sRGB hex so computed styles stay `rgb()`.

### Primary
- **Terracotta** (#ad4828, oklch 0.53 0.14 38): your next action and where you are. The one primary button per screen (Confirm, Approve, Export, Download), the current step's number, "HERE", the current queue card's wash (#ffe9de). White-on-terracotta text is 5.5:1.

### Secondary
- **Marigold** (#fce8b8 wash, #eec05b fill, #6c4302 ink; oklch 0.935 0.065 88 / 0.42 0.09 70): waiting for you. Queued blocks, what held a block, the estimated review, the waiting segment of the progress bar, "Mixed subjects", where two readings differ on the page.

### Tertiary
- **Sage** (#daf1dd wash, #62946c mid, #295233 ink; oklch 0.935 0.035 150 / 0.40 0.07 150): cleared, by the checks (hatched) or by you (solid). Passed checks, Ready sources, numbers verified, a finished export.
- **Brick** (#ac3031, oklch 0.50 0.16 25): something failed. A failed check, a content-changing edit, a failed save or request. Nothing else is red.

### Neutral
- **Stone paper** (#fbfaf7): the page background.
- **Raised** (#fffefb): cards, panes, the queue card at rest.
- **Rail** (#f5f2ed) and **Sunk** (#f8f5f1): the step rail, the page band, headers inside lists.
- **Ink** (#27201a, 15:1 on paper) and **Muted** (#625952, 6.6:1): all text. No text colour is lighter than Muted.
- **Line** (#d9d3cc) for dividers; **Line strong** (#867f77, 3.8:1) for every control boundary and checkbox.
- **Focus blue** (#0961bb): the 2px keyboard focus ring, and nothing else.

### Named Rules
**The One Meaning Rule.** Each hue has one job. Terracotta never marks a problem, marigold never marks an action, and blue is focus only. If a new state needs colour, it borrows the meaning, not the hue.

**The Red Is Earned Rule.** Brick appears only when a check or a write actually failed. A passed check, even a critical one, wears a sage tick and the word "Passed".

**The Never Colour Alone Rule.** Every coloured state also carries a word, a tick, a cross, a hatch or the drawn attention mark.

## 3. Typography

**App Font:** the system sans (system-ui, -apple-system, Segoe UI)
**Manual Font:** Atkinson Hyperlegible, bundled in `frontend/src/assets/fonts/` (SIL OFL), never fetched at runtime
**Id Font:** the system monospace

**Character:** a plain, native sans for the tool, and a hyperlegible face for the manual's words that separates 0/O and 1/l/I, so "4471-A" and "0.05" cannot be misread.

### Hierarchy
- **Title** (600, 22px, 1.3): one per screen ("Choose what goes into your knowledge base").
- **Heading** (600, 18px, 1.4): sections and the welcome steps.
- **Body** (400, 15px, 1.5): app copy, capped at 62 to 70ch.
- **Label** (600, 12px, 0.07em, uppercase): section eyebrows ("WHY THIS NEEDS YOU", "THE PAGE, AT THIS BLOCK").
- **Manual** (400, 18px, 1.7, Atkinson Hyperlegible): the extracted text, readings, excerpts, proposals, the edit box; numbers bolded.
- **Id** (400, 12px, mono): block ids, figure ids, model names; always present, never the headline.

### Named Rules
**The Two Voices Rule.** If the words came from the manual, they are set in Atkinson Hyperlegible. If the app wrote them, they are in the system sans. Never mix within one line.

## 4. Elevation

Flat by default; depth comes from tonal layers (sunk, paper, raised). One soft shadow (`lift`) marks the few surfaces you act on: the next-step card, the Scope receipt, the magnified page strip and the export summary. Dialogs use a single deeper shadow over a 38% ink scrim.

### Shadow Vocabulary
- **Lift** (`box-shadow: 0 1px 2px oklch(0.3 0.02 60 / 0.08), 0 8px 24px -16px oklch(0.3 0.03 60 / 0.35)`): the next-step card, receipt, page strip, export summary.
- **Key** (`box-shadow: 0 1px 0 var(--line)`): keycaps.
- **Dialog** (`box-shadow: 0 24px 60px -20px rgb(39 32 26 / 0.45)`): Help, Flag block, Attach a figure.

### Named Rules
**The Flat Until Touched Rule.** If two neighbouring surfaces both have shadows, one of them is wrong.

## 5. Components

### Buttons
- **Shape:** gently rounded (12px), at least 44px tall for primary actions.
- **Primary:** terracotta with near-white text and its keycap inside ("Approve A and mark its numbers checked"); hover deepens to #953a1c over 150ms ease-out-quart.
- **Secondary:** raised background, Line strong border, ink text, keycap inside.
- **Quiet:** text only in Muted ("I have used this before", "Select all").
- **Focus:** 2px focus-blue ring with a 2px offset on every control.

### Chips and status words
- **Style:** pill (999px), 12px semibold; waiting = marigold wash, cleared = sage wash, failed = brick wash with a cross. Reasons on queue cards are words separated by "·", the specific word in the manual face.

### Cards / Containers
- **Corner Style:** 12 to 16px.
- **Background:** raised on paper; sunk for bands and list headers.
- **Border:** 1px Line; held evidence uses the marigold line, failed evidence the brick line.
- **Internal Padding:** 12 to 20px; lists use dividers, never nested cards.

### Inputs / Fields
- **Style:** raised background, 1px Line strong border, 12px radius; the edit box uses the manual face at 17px.
- **Focus:** the focus-blue ring. **Error:** a brick sentence beneath, never colour on the field alone.

### Navigation (step rail)
- 248px rail on the left from 1100px: brand and Help, the "Your next step" card (terracotta outline, raised), then the four steps as a vertical journey with a connector line (ink when done). Below 1100px it becomes a bottom sheet with the steps in a row and the next step in one line. The current step is a filled terracotta circle with "HERE"; other states are words ("216 to review", "locked: 216 to review").

### Signature: the page strip
The page image cropped to the current block and scaled so the block fills the strip width (capped at a 1700px page render), with the readings' differences shaded marigold and the least certain OCR word in a dashed outline. It sits directly above the extracted text; the small page locator beside it is the interactive "Source page" (click or S to jump); Z swaps the strip for the whole page.

### Signature: the review progress bar
One bar over everything in scope: sage solid (checked by you), sage hatched (cleared by the checks), ink hatched (flagged), marigold (waiting for you). The legend states each number in words and the server's reconciliation line sits beneath it, verbatim. Segments animate on `transform` only.

## 6. Do's and Don'ts

### Do:
- **Do** put a human title before every identifier (section heading, else document, else "Page 9, paragraph") and keep the id beside it in 12px mono.
- **Do** say what will happen before it happens: "Approve, and mark its numbers checked"; "Scoring starts and Verify opens straight away."
- **Do** show both OCR readings as labelled lines in the manual face, with the differing words marked.
- **Do** keep every count a server count, and keep the reconciliation line under any total.
- **Do** respect `prefers-reduced-motion`: every transition drops to zero.

### Don't:
- **Don't** build "consumer onboarding carousels and confetti": the welcome is one inline band, shown once per project.
- **Don't** show "a single 'confidence' number with no reason": a score always follows a sentence and names its threshold.
- **Don't** drift toward "dark 'hacker' dashboards" or "marketing gradients": light stone paper, no gradient fills (hatches only to mark state).
- **Don't** colour a passed check red or tag it with a red "critical" chip.
- **Don't** use exclamation marks, em dashes, hype or a "time left" estimate.
- **Don't** use side-stripe borders, glass, or nested cards.
- **Don't** fetch fonts at runtime; the product runs offline.
