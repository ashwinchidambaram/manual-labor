# Manual Labor user guide

> Generated from frontend/src; edit there (onboarding/guide.ts, onboarding/hints.ts, hotkeys.ts), then run `npm run gen-guide` in frontend/. A test fails when this file and the source disagree.

## Getting started

Manual Labor turns PDF and DOCX manuals into a reviewed knowledge base in four steps. The same text is shown in the app's guide panel and in Help.

### 1. Choose what goes into your knowledge base

Screen: /scope (key `1`)

Every block you select becomes text in an article. Suggested topics and Document structure are two views of the same blocks: switching views never changes the selection, and each view shows how much of a group is selected.

What to do:

1. Move through the list with `j` and `k`. `Space` selects or clears a row; `a` selects everything.
2. `t` switches views. Low cohesion means a topic mixes subjects: check it in Document structure.
3. Unassigned holds the blocks no topic claimed. They are listed here, never dropped.
4. Estimated review is how many selected blocks will need a person. `g` confirms: scoring starts and Verify opens at once.

Why you can trust this:

- Under each document a line adds up its blocks: parsed = headers and footers + blocks in topics + unassigned.
- Choosing topics never changes the text. It only decides which blocks are reviewed and exported.

### 2. Review what the checks could not clear

Screen: /verify (key `2`)

The queue lists only the blocks the machine is unsure about, worst first, and each card says why. Blocks with numbers, units or part numbers are always queued: OCR mistakes in numbers are likely and a language model cannot see them.

What to do:

1. `a` approves. On a block with numbers it also records that you checked the numbers.
2. `e` edits and `Ctrl/Cmd+Enter` saves. `f` flags the block with a category. `j` skips, `k` goes back.
3. `t` shows every change cleanup made against the raw parse.
4. The slider only shows auto-approved blocks for a second look. It never changes their status.
5. Figures: `g` focuses the figure rail. Attach a figure re-attaches, `x` detaches, `c` adjusts the crop.

Why you can trust this:

- Checks on this block lists each deterministic check and its result. A check that has not run says so; it is never shown as passed.
- The status line adds up: in scope = to review + auto-approved + done + flagged.

### 3. Hand flagged blocks to a model

Screen: /agent (key `3`)

Flags you raised can be handed to a model, one fresh call per item. Every proposal is re-checked by the same deterministic checks, and failed checks are shown, not hidden.

What to do:

1. Run the agent pass for the open flags. You can keep reviewing while it runs.
2. Accept, edit or reject each proposal. A rejected item goes back to the queue with what was tried.
3. Calibration shows how often you edited blocks at each confidence level and suggests a threshold. It never changes the threshold for you.

Why you can trust this:

- A proposal's model rationale is shown next to the evidence it quotes; quotes not found in the source are struck through.

### 4. Export the reviewed knowledge base

Screen: /export (key `4`)

Export unlocks when no flag is open and nothing in scope is still waiting for review. While it is locked, the screen lists exactly what blocks it, with a link to each.

What to do:

1. Resolve the listed blocks in Verify or on the Agent screen.
2. Or export anyway: an override needs a reason, and every overridden block is listed in manifest.json.
3. Download the zip and compare its SHA-256 with the one shown.

Why you can trust this:

- The export contains only text a person or the checks accepted, plus any blocks you overrode with a recorded reason.

## How it works

- **The same file gives the same result.** Parsing, IDs, scoring, the faithfulness check and assembly are deterministic code.
- **Cleanup cannot rewrite your text.** It may only join hyphenated lines, fix whitespace, remove headers and footers, normalise bullets and fix reading order. Any other change to characters or numbers fails the faithfulness check, and the block is queued with the diff.
- **Confidence comes from disagreement, not from a model's opinion of itself.** Two parsers, the text layer against OCR, and a separate verifier are compared. No model rates its own output.
- **Every model output is validated before you see it.** Proposals and cleanups go through the same deterministic checks as everything else.
- **Learning from your edits is visible.** Each block shows which learned rules touched it (Why did this change?), and each rule can be disabled or reset.
- **Nothing is dropped silently.** Counts reconcile on every screen, and every block ends up in an article or in the unassigned list.

## Keyboard shortcuts

Every key below comes from the single hotkey map (frontend/src/hotkeys.ts). Keys never fire while you type in a text field, except where noted.

### Everywhere

| Keys | Action |
|---|---|
| `?` | Show or hide this help |
| `1` | Go to Scope |
| `2` | Go to Verify |
| `3` | Go to Agent |
| `4` | Go to Export |

### Scope screen

| Keys | Action |
|---|---|
| `t` | Switch between topics and document structure |
| `Esc` | Focus the group list |
| `o` | Focus the sources list |
| `m` | Focus the model panel (again: back to the list) |
| `u` | Focus the selection summary |
| `s` | Cycle article split: per topic / per document |
| `a` | Select every block |
| `n` | Clear the selection |
| `g` | Confirm scope and go to Verify |

### Inside the group list

| Keys | Action |
|---|---|
| `j` / `Down` | Next row |
| `k` / `Up` | Previous row |
| `Home` | First row |
| `End` | Last row |
| `Right` / `l` | Expand, or go to the first child (structure view) |
| `Left` / `h` | Collapse, or go to the parent (structure view) |
| `Space` | Toggle the row (partial selects the rest) |
| `Enter` | Select only this row |
| `Shift+A` | Select the whole document of this row |

### Verify screen

| Keys | Action |
|---|---|
| `a` | Approve the current block |
| `e` | Edit the current block (Ctrl or Cmd + Enter saves) |
| `f` | Flag the current block |
| `j` | Skip the current block |
| `k` | Go back to the previous block |
| `t` | Switch between text and diff against raw |
| `s` | Focus the current block on the source page |
| `g` | Focus the figure rail |
| `/` | Cycle the queue sort |
| `[` | Review fewer auto-approved blocks (view filter down) |
| `]` | Review more auto-approved blocks (view filter up) |
| `z` | Zoom the source page |
| `Esc` | Cancel the edit or mode, else back to the queue |

### Verify: queue

| Keys | Action |
|---|---|
| `Down` | Next block in the queue |
| `Up` | Previous block in the queue |
| `Home` | First block in the queue |
| `End` | Last block in the queue |

### Verify: source pane

| Keys | Action |
|---|---|
| `Right` / `Down` | Next block on the page |
| `Left` / `Up` | Previous block on the page |
| `Enter` | Make the focused block current |

### Verify: figure rail

| Keys | Action |
|---|---|
| `Down` | Next figure |
| `Up` | Previous figure |
| `x` | Detach the focused figure from this article |
| `c` | Adjust the crop of the focused figure |

### Verify: editing

| Keys | Action |
|---|---|
| `Ctrl/Cmd`+`Enter` | Save the edit |

### Flag dialog

| Keys | Action |
|---|---|
| `1` | Category: wrong text |
| `2` | Category: missing figure |
| `3` | Category: wrong grouping |
| `4` | Category: bad crop |
| `5` | Category: table structure |
| `Enter` | Submit the flag (when not typing a note) |
| `Ctrl/Cmd`+`Enter` | Submit the flag from anywhere |

### Inside a widget

| Keys | Where | Action |
|---|---|---|
| `Down` / `Up` | Sources list | Move between sources |
| `Left` / `Right` / `Up` / `Down` | Radio groups (view, article split, model tier) | Move to and select the neighbouring option |
| `Left` / `Right` | Help tabs | Switch between Guide, Keyboard shortcuts and Glossary |

## Glossary

- **Scope (step 1)** (`1`): Choose which topics or sections become articles.
- **Verify (step 2)** (`2`): Review the blocks the checks could not clear.
- **Agent (step 3)** (`3`): Hand flagged blocks to a model and review its proposals.
- **Export (step 4)** (`4`): Build the knowledge base zip once nothing is left to review.
- **Help** (`?`): Getting-started guide, keyboard shortcuts and this glossary.
- **Grouping view** (`t`): Two views of the same blocks. Switching never changes what is selected.
- **Article split** (`s`): Whether articles follow topics or whole documents. It changes the article count, not the selected blocks.
- **Select all** (`a`): Select every block of every document.
- **Clear selection** (`n`): Clear the whole selection. Asks twice so it cannot happen by accident.
- **Confirm scope** (`g`): Saves the selection, starts scoring and opens Verify. Review can start as soon as the first document is scored.
- **Add documents**: Add PDF or DOCX files. Parsing runs in the background while you keep working.
- **Model tier**: Use this tier's models for every task. Stages that depend on the models are marked to re-run.
- **Review filter** (`]`): Also lists auto-approved blocks below this confidence for a second look. Their status does not change.
- **Queue order** (`/`): Worst first, by page, or figures only.
- **Original vs cleaned** (`t`): The diff shows every change cleanup made to the raw parse. Grey changes are allowed normalisation.
- **Approve** (`a`): Accept the text as shown. On a block with numbers this records that you checked them.
- **Edit** (`e`): Correct the text. Your edit is checked too: a change to content or numbers asks you to confirm.
- **Flag** (`f`): Mark the block as wrong: text, figure, grouping, crop or table. Open flags lock the export.
- **Skip** (`j`): Leave the block queued and move on.
- **Back** (`k`): Return to the previous block.
- **Attach a figure**: Pick a figure from this document and attach it to the current article.
- **Export**: Builds the zip from accepted text and records the build in the action log.
- **Override reason**: Why you are exporting with blocks not yet reviewed. It is written into manifest.json.
- **Reason chip**: A signal that kept this block from auto-approval. Red chips are critical: the block cannot pass while they are low.
- **Block status**: Queued waits for you; auto-approved was cleared by the checks; approved, edited and flagged are your decisions.
- **Cohesion**: How closely a topic's blocks belong together, from 0 to 1. Low cohesion means the topic may mix subjects.
- **Coverage**: How much of this group is in your selection.
- **Numbers verified by you**: You approved this block after checking its numbers against the source page.
- **Attach rule**: How a figure was matched to its article: a caption reference, proximity on the page, or by hand.
- **Learned rules**: Rules learned from your earlier edits that were used on this block. Each one can be disabled.
- **Extraction method**: How a figure was extracted: a native image, a vector render, or a crop of the page image.
- **Signal: low OCR**: Average OCR confidence over the block's words.
- **Signal: weak OCR word**: OCR confidence of the least certain word in the block.
- **Signal: text layer ≠ OCR**: How closely the PDF text layer and OCR agree on this region.
- **Signal: parsers disagree**: How closely the two parsers' readings of this block agree.
- **Signal: reading order**: How safe the reading order is; columns and wrapped text lower it.
- **Signal: table shape**: Whether the table's rows and columns line up consistently.
- **Signal: garbled text**: How free the text is of broken characters or a wrong encoding.
- **Signal: cleanup changed content**: Whether cleanup kept the text, changing only spacing, hyphenation, headers or reading order.
- **Signal: figure crop**: How the figure was extracted; a crop of the page image scores lower than a native image.
- **Signal: low-res figure**: Whether the figure image has enough resolution.
- **Signal: weak figure match**: How strong the rule is that matched the figure to this article.
- **Signal: numeric spec**: Blocks with numbers, units or part numbers are always reviewed by a person.
- **Signal: verifier disagrees**: How closely a separate verifier model's reading agrees.

## Reset the guide

The getting-started panel opens once per project and stays hidden after Hide guide. To see it again, open Help (`?`), stay on the Guide tab and choose Show guide panel. From a script: `PUT /api/ui/guide` with the body `{"seen": false}`. If the server cannot store the flag, the browser keeps it in localStorage instead.
