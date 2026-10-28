# Manual Labor — Spec

> Turn any document (manuals first) into a knowledge base: faithful text articles, figures extracted separately and referenced by stable IDs, with a human-in-the-loop review that only asks the human to look where the machine is unsure.

Working name: **Manual Labor** (package `manuallabor`, CLI `labor`). Rename freely.

This spec is deliberately high-level: it defines features, contracts, and acceptance criteria. Module design is yours — see `CLAUDE.md` for how to plan and verify each one.

---

## 1. North Star

A human drops in a document, picks what they care about, spends a few minutes reviewing only the uncertain parts, and gets a zip of Markdown articles + images + manifest that is ready to load into a KB.

Three things the whole system is optimized for, in order:

1. **Faithfulness.** Article text is the source text, cleaned — never rewritten, summarized, or embellished. Numbers never change silently.
2. **Reviewer time.** The human should look at the smallest possible set of items, with the evidence needed to decide in seconds.
3. **Portability.** Runs fully local (Ollama / vLLM / llama.cpp) or against APIs (Anthropic, OpenAI-compatible). Output is plain files any KB can ingest.

## 2. Scope

**v1 (build this)**
- Input: born-digital PDF. Scanned PDF via OCR. DOCX.
- Output: zip of Markdown articles, `images/`, `manifest.json`.
- Full HIL loop: Scope → Verify → Agent pass → Export.
- Local + API model support with hardware-aware suggestions.
- Multi-document projects (figures carry doc/model provenance).

**Explicitly out of v1**: HTML/web ingestion, chat/retrieval over the KB, user accounts/multi-tenant, target-specific KB adapters (Zendesk, Confluence, etc.). Design so these can be added without rework.

## 3. Core concepts

| Term | Definition |
|---|---|
| **Project** | A folder containing N source documents, their parse results, review state, and exports. Everything about a project lives on disk under one directory so it can be zipped, moved, resumed. |
| **Block** | The atomic unit of extraction. One heading / paragraph / list / table / figure / caption, with `doc_id`, `page`, `bbox`, `type`, `raw_text`, `clean_text`, `confidence`, `signals[]`, `status`. Blocks are never split or merged after parsing; grouping happens above them. |
| **Figure** | A block of type `figure` plus an extracted image file and a sidecar record (see §6). |
| **Group** | An ordered set of block IDs that becomes one article. Two grouping sources: *structure* (heading tree) and *topic* (LLM-proposed). Both are views over the same blocks, so a selection in one is expressible in the other. |
| **Article** | One Markdown file assembled from a group's approved blocks. |
| **Flag** | A human-raised issue on a block or figure: category + optional note. Flags are what the agent pass consumes. |

## 4. Pipeline

```
ingest → parse → score → group → [HIL: scope] → clean+attach → score → [HIL: verify ⇄ agent pass] → assemble → export
```

### 4.1 Ingest
- Accept one or more files. Fingerprint each (sha256). Detect type: born-digital PDF vs scanned (text layer coverage per page), DOCX.
- Extract document metadata: title, product/model (from title page, headers, filename — LLM-inferred as fallback, marked as inferred).

### 4.2 Parse (two parsers, always)
- Run **two independent parsers** on every PDF (e.g., Docling and PyMuPDF; swap freely). Their disagreement is the single most useful confidence signal we have, so this is not optional.
- Scanned pages: render at ≥300 DPI → OCR (Tesseract or RapidOCR/PaddleOCR; must retain per-word confidence). For born-digital pages with a text layer, *also* OCR the render in the background and compare — this catches corrupted text layers (`3S` vs `35`).
- Produce blocks with reading order, bbox, type. Detect and strip repeating headers/footers (record what was stripped).
- Tables: emit structured cells + a Markdown rendering; keep row/col counts from both parsers.
- DOCX: parse structure directly (python-docx / mammoth); images come out natively; no OCR needed.

### 4.3 Figure extraction — highest quality available, in this order
1. **Native raster**: if the figure region is a single embedded image, extract the original bytes at original resolution (PyMuPDF xref). Method = `native`.
2. **Vector**: if the region is vector drawing commands, export the clipped region as SVG, plus a PNG render at 300 DPI for consumers that can't use SVG. Method = `vector`.
3. **Raster crop**: otherwise render the page at 300 DPI and crop the bbox with a small margin. Method = `crop`.

Record the method; `crop` lowers the figure's confidence. Dedupe by perceptual hash across the project (same diagram in three manuals → one file, three references).

### 4.4 Score (see §5 — this is the heart of the HIL design)

### 4.5 Group
- **Structure view**: heading tree from the parser, with page ranges.
- **Topic view**: LLM proposes topics over block summaries (embed → cluster → label, then an LLM pass to name clusters and assign stragglers). Every block is assigned to exactly one topic or to `unassigned`. Each topic reports: page ranges, block/figure counts, which structure sections it spans, and a cohesion score (mean intra-cluster embedding similarity).
- Both views select *blocks*. Switching views shows coverage of the current selection in the other view.

### 4.6 Clean + attach (runs only on selected blocks)
- **Clean**: dehyphenate line breaks, join wrapped lines, strip header/footer remnants, normalize whitespace and bullets, reconstruct tables. LLM may be used, but its output is subject to the faithfulness check (§5.2) — a cleanup that fails the check is rejected and the raw text is used with a low confidence.
- **Attach figures** to articles, in priority order: explicit caption reference in text ("see Fig. 3") → caption text match → same-section proximity. Record which rule fired; proximity-only = low confidence.
- **Caption/describe**: for each figure, store original caption (if any) and a VLM-generated description (alt text for text-only retrieval) + tags. Descriptions are clearly labelled as generated.

### 4.7 Assemble + export
- One article per group (or one per document, per project setting).
- Markdown with YAML frontmatter (§6). Figures referenced inline.
- `manifest.json` ties everything together. Zip it all.

## 5. Knowing when the machine is unsure

A single confidence number per block is the product of independent signals. Every signal is logged on the block so the reviewer sees *why* — never just a number.

### 5.1 Signals (per block)
| Signal | How it's computed | Note |
|---|---|---|
| `ocr_mean`, `ocr_min` | From the OCR engine's per-word confidences | `ocr_min` matters more than the mean — one bad number is a bad article |
| `textlayer_vs_ocr` | Token-level agreement between PDF text layer and OCR of the render | Catches corrupt text layers on born-digital PDFs |
| `parser_agreement` | Token-level diff between the two parsers' output for the same region | Strongest general signal |
| `reading_order_risk` | Multi-column detection, bbox overlap, parsers disagree on block order | |
| `table_consistency` | Row/col counts agree across parsers; no ragged rows; header detected | |
| `garbage_ratio` | Share of tokens that are non-dictionary / symbol soup | Language-agnostic fallback: character-class entropy |
| `faithfulness` | See §5.2 | Applied after cleanup |
| `figure_method` | `native` > `vector` > `crop` | |
| `figure_attach_rule` | `caption_ref` > `caption_match` > `proximity` | |
| `has_numeric_spec` | Regex: units, part numbers, tolerances, torque, voltages | **Rule, not score**: these blocks are always queued for human review regardless of confidence. OCR errors in numbers are both likely and invisible to language models. |
| `llm_verifier` | Optional: a *separate* model call given raw + clean, asked a constrained question ("Does the cleaned text change any fact, number, or step? Answer with the differing span or NONE") | Never ask a model to rate its own output. Use it as a second reader, and treat its answer as one signal among many. |

### 5.2 Faithfulness check (deterministic, always runs)
Cleanup may only: join hyphenated line breaks, remove whitespace/newlines, remove detected header/footer strings, normalize bullet glyphs, and reorder for reading-order fixes. Therefore:
- Align `clean_text` to `raw_text` at character level (difflib / Levenshtein alignment). Any insertion that is not whitespace, and any deletion that is not whitespace/hyphen/known header-footer string, is a violation.
- All numeric tokens in raw must appear in clean with the same multiset (unless the block was flagged as a text-layer-vs-OCR conflict, in which case the chosen variant is recorded explicitly).
- Report an alignment ratio; threshold failures force confidence to the floor and attach the diff.

### 5.3 Combining
- Default: `confidence = min(critical signals) × geometric mean(soft signals)`, clamped to [0,1]. A single critical failure (faithfulness violation, parser agreement < 0.8 on a numeric block) should dominate — this is why we take a min over critical ones. Make the formula a pure function in one place with unit tests.
- Project-level **threshold** (default 0.85). Blocks above it are auto-approved; below it are queued, sorted worst-first. The human can drag the threshold to 0 to see everything.

### 5.4 Calibration
- Record every human decision (approve as-is / edit / flag) with the block's score and signals.
- Per project and globally, compute edit rate per score bucket. Suggest a threshold where observed edit rate drops below a target (e.g., 2%). Show this to the user; never change the threshold silently.

### 5.5 Agent pass
- Input per flagged item: raw text from both parsers, page render, block signals, flag category, human note.
- A fresh model call per item (no shared context between items). Must return: proposal, evidence it relied on, and a one-line rationale.
- Every proposal is re-run through §5.2 and the relevant signals before display. Proposals that fail are shown with the failure, not hidden.
- Human accepts / edits / rejects each. Rejected proposals go back to the queue with the proposal attached so the next round sees what was tried.

## 6. Output contracts

### 6.1 IDs (agent-friendly: greppable, stable, self-describing)
- Document: `<slug>` — lowercase, from filename/title, unique in project (e.g. `acme-x200-service`).
- Block: `b-<docslug>-p<page:03d>-<n:02d>` (e.g. `b-acme-x200-service-p042-03`).
- Figure: `FIG-<docslug>-p<page:03d>-<n:02d>` (e.g. `FIG-acme-x200-service-p042-01`). Uppercase prefix so it stands out in prose and is trivially regex-able (`FIG-[a-z0-9-]+-p\d{3}-\d{2}`).
- Article: `<docslug>--<topic-slug>` or `<docslug>` for one-per-document.
IDs never change after parsing. Re-parsing the same file (same sha256) yields the same IDs.

### 6.2 Article Markdown
```markdown
---
id: acme-x200-service--belt-tension
title: Belt tension & drive maintenance
source_doc: acme-x200-service
source_file: X200_Service_Manual_rev4.pdf
product_model: Acme X200
pages: [41, 42, 43, 44, 45]
sections: ["5.1"]
figures: [FIG-acme-x200-service-p042-01, FIG-acme-x200-service-p042-02]
blocks: 7
review: { approved: 7, edited: 1, overrides: 0 }
generated_at: 2026-10-28T18:00:00Z
---

# Belt tension & drive maintenance

To adjust belt tension, loosen the four M8 bolts on the motor mount …

![FIG-acme-x200-service-p042-01 — Belt tension adjustment points](images/acme-x200-service/FIG-acme-x200-service-p042-01.png)

Tighten bolts to 35 N·m in a cross pattern.
```
The alt text always begins with the figure ID, followed by ` — ` and the caption (original if present, else generated). This keeps the reference useful in plain-text contexts and lets an agent map image → manifest record with one regex.

### 6.3 Figure sidecar (`images/<docslug>/<FIG-ID>.json`)
```json
{
  "id": "FIG-acme-x200-service-p042-01",
  "file": "FIG-acme-x200-service-p042-01.png",
  "svg": null,
  "source_doc": "acme-x200-service",
  "product_model": "Acme X200",
  "page": 42,
  "bbox": [72.0, 410.2, 523.5, 688.0],
  "extraction": "native",
  "width": 1800, "height": 1200,
  "phash": "c3a1…",
  "caption_original": "Figure 1. Belt tension adjustment points",
  "description_generated": "Side view of motor mount showing four M8 bolts and belt deflection measurement point.",
  "tags": ["belt", "motor mount", "tension", "maintenance"],
  "articles": ["acme-x200-service--belt-tension"],
  "attach_rule": "caption_ref",
  "confidence": 0.96,
  "review": "approved"
}
```

### 6.4 Zip layout
```
<project>-kb.zip
├── articles/*.md
├── images/<docslug>/FIG-*.png|svg + FIG-*.json
├── manifest.json        # project, docs, articles, figures, review stats, model+threshold used, overrides
└── README.md            # what this is, how IDs work, how to ingest
```

## 7. HIL UI

A local web app. Three screens, keyboard-first. See the design mockup for the layout; the behaviors below are the contract.

### 7.1 Scope
- Sources list with parse status and OCR quality warning.
- Toggle: *Suggested topics* / *Document structure*. Same blocks underneath; selection persists across the toggle; the opposite view shows coverage (% of each section included).
- Each topic shows pages, block/figure counts, sections spanned, cohesion. Low-cohesion topics are visibly marked.
- Catch-all "Unassigned blocks" topic.
- Article split setting (per topic / per document).
- Live "what you will get" counts and an estimated review load (blocks under threshold).
- Model panel: shows the chosen model per task (cleanup / grouping / vision) and the hardware-based suggestion.

### 7.2 Verify
- Status strip: queued / auto-approved / flagged counts; threshold slider; sort (worst-first, by page, figures only).
- Four panes: **queue** (block cards with confidence + reason chips) · **source** (page render with the block outlined; parser-disagreement spans highlighted; click any block on the page to jump) · **extracted** (inline edit; *Text* / *Diff vs raw* toggle; "Why this needs you" signal list) · **figures** rail for the current article (thumbnail, ID, caption, method, attach rule, confidence; re-attach by drag or picker; adjustable crop bbox).
- Actions: Approve `A`, Edit `E`, Flag `F`, Skip `J`, Back `K`. Flag = category chips (wrong text, missing figure, wrong grouping, bad crop, table structure) + optional note.
- Approving a numeric block marks its numbers as human-verified in the manifest.
- State autosaves on every action; reopening the project resumes at the same spot.

### 7.3 Agent pass
- "Run agent pass" is available whenever ≥1 flag is open. Shows proposals as before/after with the checks that were re-run (pass/fail per check). Accept / Edit / Reject per item, "Accept all passing" bulk action.
- Calibration card: observed edit rates by score bucket, suggested threshold, apply-to-next-doc button.

### 7.4 Export
- Unlocked at zero open flags. Override allowed; overrides are listed in `manifest.json`.
- Produces the zip; shows a summary (articles, figures, pages covered, review stats).

## 8. Models & hardware

- One provider interface for chat, vision, and embeddings. Use LiteLLM (or equivalent) so Ollama, vLLM, llama.cpp-server, OpenAI-compatible, and Anthropic are config, not code.
- Task → model mapping in project config: `cleanup`, `grouping`, `vision`, `verifier`, `embeddings`. Each can be a different provider.
- **Hardware probe** on first run: CPU, RAM, GPU + VRAM (NVIDIA via nvidia-smi, Apple unified memory via sysctl, AMD via rocm-smi), disk. Produce a suggestion table (small/medium/large option per task with expected speed), and an "all-API" option. Never auto-install; show commands.
- Every LLM call is logged (task, model, tokens, latency, input hash) so a run is reproducible and cost is visible.

## 9. Non-functional

- **Resumable**: every stage writes to disk; killing the process never loses more than the current block.
- **Deterministic where possible**: parsing, scoring, IDs, and the faithfulness check are pure functions of the input. LLM calls use temperature 0 and are cached by input hash.
- **Offline-capable**: with local models configured, no network calls at all.
- **Performance target**: a 200-page born-digital manual parses and scores in < 5 minutes on a laptop without GPU (LLM steps excluded); the UI stays responsive on 1,000+ blocks.
- **Packaging**: `uv run labor serve ./my-project` starts everything; `labor ingest`, `labor parse`, `labor export` for headless use. Single Python package + built frontend assets.
- **Tests**: see `CLAUDE.md`. Golden fixtures of real-world-like PDFs (born-digital, scanned, two-column, table-heavy, figure-heavy) live in `tests/fixtures/` and are the acceptance bar.

## 10. Suggested stack (change with reason)

- Python 3.12, FastAPI, SQLite (project state) + files on disk, Pydantic models for every contract in §6.
- Parsing: Docling + PyMuPDF; OCR: RapidOCR (default, pip-installable) with Tesseract optional; DOCX: python-docx.
- Embeddings: local sentence-transformers by default; provider-switchable.
- LLM: LiteLLM.
- Frontend: React + TypeScript + Vite, Tailwind, pdf.js for page rendering, keyboard handling via a single hotkey map.
- Images: Pillow, imagehash (phash), cairosvg for vector → PNG.

## 11. Acceptance criteria (v1 done when)

1. Each fixture PDF round-trips: ingest → parse → auto-select all → export, with zero faithfulness violations on auto-approved blocks.
2. On the scanned fixture, every block whose OCR output differs from ground truth has confidence below the default threshold (i.e. it reaches the queue). Measure and report recall.
3. On the figure-heavy fixture, ≥95% of figures extract by `native` or `vector`, and every figure with a caption reference attaches to the right article.
4. The Verify screen lets a reviewer process 20 queued blocks using only the keyboard.
5. An agent pass on 5 seeded flags returns proposals, and every proposal displays its re-check results.
6. Switching the Scope toggle preserves selection and shows correct coverage.
7. The export zip validates against the manifest schema; every `FIG-` reference in every article resolves to a file and a sidecar.
8. Fully local run (Ollama models) completes end-to-end with network disabled.
