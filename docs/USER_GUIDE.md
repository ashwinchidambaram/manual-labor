# Manual Labor user guide

> Generated from frontend/src; edit there (onboarding/guide.ts, onboarding/hints.ts, hotkeys.ts), then run `npm run gen-guide` in frontend/. A test fails when this file and the source disagree.

## Getting started

Manual Labor turns PDF and DOCX manuals into a reviewed knowledge base in four steps. The same text is shown in the app's guide panel and in Help.

### 1. Choose what goes into your knowledge base

Screen: /scope (key `1`)

Every block you select becomes text in an article. Suggested topics and Document structure are two views of the same blocks: switching views never changes the selection, and each view shows how much of a group is selected.

What to do:

1. Move through the list with `J` and `K`. `Space` selects or clears a row; `A` selects every block.
2. `T` switches views. Mixed subjects means a topic's blocks cover different subjects: check it in Document structure.
3. Unassigned holds the blocks no topic claimed. They are listed here, never dropped.
4. Estimated review is how many selected blocks will need a person. `G` confirms: scoring starts and Verify opens at once.

Why you can trust this:

- Under each document a line adds up its blocks: blocks found = blocks in topics + blocks not placed in a topic + page headers and footers, which are left out.
- Choosing topics never changes the text. It only decides which blocks are reviewed and exported.

### 2. Review what the checks could not clear

Screen: /verify (key `2`)

The queue lists only the blocks the checks could not clear, most doubtful first, and each card says why. Blocks with numbers, units or part numbers are always queued: OCR mistakes in numbers are likely and a language model cannot see them.

What to do:

1. `A` approves. On a block with numbers it also records that you checked the numbers.
2. `E` edits and `Ctrl/Cmd+Enter` saves. `F` flags the block with a category. `J` skips, `K` goes back.
3. `T` shows every change cleanup made against the raw parse.
4. The slider only shows auto-approved blocks for a second look. It never changes their status.
5. Figures: `G` focuses the figure rail. Attach a figure re-attaches, `X` detaches, `C` adjusts the crop.

Why you can trust this:

- Why this needs you lists what held the block, with the evidence: the two readings line by line, the least certain word. Checks that found nothing wrong are marked Passed, and a check that has not run says so; it is never shown as passed.
- The progress bar and the line under it add up: in scope = to review + auto-approved + done + flagged + rejected. The server counts each part separately, and a mismatch is shown as a warning.

### 3. Hand flagged blocks to a model

Screen: /agent (key `3`)

An agent pass works through your open flags. Each flagged block goes to a model with your note, and the model proposes a fix. Its proposal is checked again by the same checks before you see it, and a check that fails is shown, not hidden.

What to do:

1. Run the agent pass for the open flags. You can keep reviewing while it runs.
2. Accept, edit or reject each proposal. Accept is only offered when every re-check passed.
3. Rejecting a proposal leaves its flag open: the item stays on this screen for the next agent pass with what was tried and your reason, and the export stays locked until the flag is resolved.
4. Calibration shows how often you edited blocks at each confidence level and suggests a threshold. It never changes the threshold for you.

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

- **Parsing and checking are code, not a model.** Parsing, IDs, scoring, the faithfulness check and assembly are deterministic code. Model calls (cleanup, topic names, figure descriptions, the agent and the optional verifier) run at temperature 0 and are cached by their input, so a re-run reuses the same answers while the cache is kept.
- **Cleanup cannot rewrite your text.** Cleanup may only change whitespace, join words hyphenated across a line break, remove known headers and footers, fix reading order only where the other parser or OCR read the block in the cleaned order (page layout alone is not evidence), turn ligatures, Unicode variants and soft hyphens into plain text, rebuild table layout without changing any cell, and normalise list bullets. Where the PDF text layer and OCR read a number differently by a look-alike character (0 and O, 1 and l) and the other reading confirms it, the number chosen between text layer and OCR is recorded, not failed. Any other change to characters or numbers fails the faithfulness check, and the block is queued with the diff.
- **Confidence comes from disagreement, not from a model's opinion of itself.** Two parsers, the PDF text layer against OCR, and a separate verifier model when one is configured are compared. No model rates its own output.
- **Model text is checked before you see it.** Cleaned text and agent proposals go through the same deterministic checks as everything else. Figure descriptions are only checked against their schema, not against the image.
- **Learning from your edits is visible.** Each block shows which learned rules touched it (Why did this change?), and each rule can be disabled or reset.
- **Nothing is dropped silently.** On Scope, each document's line adds up its parsed blocks; on Verify, the status line adds up the blocks in scope. Every block ends up in an article or in the unassigned list.

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
| `T` | Switch between topics and document structure |
| `Esc` | Focus the group list |
| `O` | Focus the sources list |
| `M` | Focus the model panel (again: back to the list) |
| `U` | Focus the selection summary |
| `S` | Cycle article split: per topic / per document |
| `A` | Select every block |
| `N` | Clear the selection |
| `G` | Confirm scope and go to Verify |

### Inside the group list

| Keys | Action |
|---|---|
| `J` / `Down` | Next row |
| `K` / `Up` | Previous row |
| `Home` | First row |
| `End` | Last row |
| `Right` / `L` | Expand, or go to the first child (structure view) |
| `Left` / `H` | Collapse, or go to the parent (structure view) |
| `Space` | Toggle the row (partial selects the rest) |
| `Enter` | Select only this row |
| `Shift+A` | Select the whole document of this row |

### Verify screen

| Keys | Action |
|---|---|
| `A` | Approve the current block |
| `E` | Edit the current block (Ctrl or Cmd + Enter saves) |
| `F` | Flag the current block |
| `J` | Skip the current block |
| `K` | Go back to the previous block |
| `T` | Switch between text and diff against raw |
| `S` | Focus the current block on the source page |
| `G` | Focus the figure rail |
| `/` | Cycle the queue sort |
| `[` | Review fewer auto-approved blocks (view filter down) |
| `]` | Review more auto-approved blocks (view filter up) |
| `Z` | Zoom the source page |
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
| `X` | Detach the focused figure from this article |
| `C` | Adjust the crop of the focused figure |

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
- **Grouping view** (`T`): Two views of the same blocks. Switching never changes what is selected.
- **Article split** (`S`): Whether articles follow topics or whole documents. It changes the article count, not the selected blocks.
- **Select all** (`A`): Select every block of every document.
- **Clear selection** (`N`): Clear the whole selection. Asks twice so it cannot happen by accident.
- **Confirm scope** (`G`): Saves the selection, starts scoring and opens Verify. Review can start as soon as the first document is scored.
- **Add documents**: Add PDF or DOCX files. Parsing runs in the background while you keep working.
- **Model tier**: Use this tier's models for every task. Stages that depend on the models are marked to re-run.
- **Review filter** (`]`): Also lists auto-approved blocks below this confidence for a second look. Their status does not change.
- **Queue order** (`/`): Most doubtful first, by page, or figures only.
- **Original vs cleaned** (`T`): The diff shows every change cleanup made to the raw parse. Grey changes are allowed normalisation.
- **Approve** (`A`): Accept the text as shown. On a block with numbers this records that you checked them.
- **Edit** (`E`): Correct the text. Your edit is checked too: a change to content or numbers asks you to confirm.
- **Flag** (`F`): Mark the block as wrong: text, figure, grouping, crop or table. Open flags lock the export.
- **Skip** (`J`): Leave the block queued and move on.
- **Back** (`K`): Return to the previous block.
- **Attach a figure**: Pick a figure from this document and attach it to the current article.
- **Export**: Builds the zip from accepted text and records the build in the action log.
- **Override reason**: Why you are exporting with blocks not yet reviewed. It is written into manifest.json.
- **Reason**: A check that kept this block from auto-approval. A critical one can hold a block on its own while it is low.
- **Block status**: Queued waits for you; auto-approved was cleared by the checks; approved, edited and flagged are your decisions.
- **Mixed subjects**: These blocks cover different subjects (cohesion, from 0 to 1, is low). Check them in Document structure.
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
- **Signal: cleanup changed content**: Whether cleanup kept the text, making only the allowed changes: whitespace, hyphenation, headers and footers, reading order, character forms, table layout and bullets.
- **Signal: figure crop**: How the figure was extracted; a crop of the page image scores lower than a native image.
- **Signal: low-res figure**: Whether the figure image has enough resolution.
- **Signal: weak figure match**: How strong the rule is that matched the figure to this article.
- **Signal: numeric spec**: Blocks with numbers, units or part numbers are always reviewed by a person.
- **Signal: verifier disagrees**: How closely a separate verifier model's reading agrees.

## Reset the guide

The welcome on Scope shows once per project and stays hidden after Start with step 1 or I have used this before. To see it again, open Help (`?`), stay on the Guide tab and choose Show the welcome again. From a script: `PUT /api/ui/guide` with the body `{"seen": false}`. If the server cannot store the flag, the browser keeps it in localStorage instead.
