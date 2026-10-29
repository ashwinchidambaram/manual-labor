# Acceptance record (SPEC section 11)

status: COMPLETE
generated: 2026-10-29T22:59:43Z
tool version: 0.1.0
uv.lock sha256: 918bc4145faed31e8d5d49254884511ca9dda0146b13c88382b2a34eab4d1f69
host: Darwin 25.5.0 arm64, 16.0 GiB RAM
mode: live (local models)
total wall time: 816 s

Every line below is output pasted from the command that produced it. NOT VERIFIED means the step did not run or printed no evidence; it is not a pass.

| AC | item | verdict | evidence |
|---|---|---|---|
| 0 | Machine checks: tests, lint, types, JSON schemas, OpenAPI | **VERIFIED** | 1631 passed, 73 skipped (counted from the progress line) |
| 1 | SPEC 11.1: each fixture round-trips; zero faithfulness violations on auto-approved blocks | **VERIFIED** | K3, K12, K13, K14 PASS; faithfulness violations / auto-approved blocks per fixture: clean 0/65, figures 0/57, manual 0/7, scanned 0/86, tables 0/33, twocol 0/44 |
| 2 | SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall) | **VERIFIED** | recall 24/24 at threshold 0.85 |
| 3 | SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly | **VERIFIED** | native=8 vector=6 crop=0 (100%); caption refs clean 3/3, twocol 3/3, figures 12/12, scanned 3/3, manual 2/2 |
| 4 | SPEC 11.4: 20 queued blocks processed with the keyboard only | **VERIFIED** | 1 passed (Playwright) |
| 5 | SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results | **VERIFIED** | PROPOSALS 5/5 with checks |
| 6 | SPEC 11.6: Scope toggle preserves selection and shows correct coverage | **VERIFIED** | 1 passed (Playwright) |
| 7 | SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar | **VERIFIED** | 124 passed, 1 skipped (counted from the progress line); OK: 52 articles, 25 figures; zip sha256 12a04817641542c5e08cd13bbdd259dd1f528fd4b0ed0e4f56d6dc4833bf3086 |
| 8 | SPEC 11.8: fully local run (Ollama), network disabled | **VERIFIED** | 0 network violations; ollama=464 other=0; negative control: 1.1.1.1:443 blocked and logged |

## AC0: Machine checks: tests, lint, types, JSON schemas, OpenAPI

verdict: **VERIFIED**: 1631 passed, 73 skipped (counted from the progress line)

command: `env -u ACCEPT_ONLY -u ACCEPT_SKIP -u ACCEPT_KEEP -u ACCEPT_DRY_RUN uv run pytest -q`  (exit 0, 811 s)

```
[... 62 earlier lines omitted ...]
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/pydantic/_internal/_generate_schema.py:1507: UserWarning: Items 'message', 'prompt_eval_count', 'eval_count' on TypedDict class '_OllamaGenerateResponse' are using the `ReadOnly` qualifier. Pydantic will not protect items from any mutation on dictionary instances.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```

command: `uv run ruff check manuallabor tests`  (exit 0, 0 s)

```
All checks passed!
```

command: `uv run mypy manuallabor`  (exit 0, 4 s)

```
Success: no issues found in 189 source files
```

command: `uv run labor schemas export --check`  (exit 0, 0 s)

```
schemas up to date
```

command: `uv run labor openapi export --check`  (exit 0, 1 s)

```
openapi up to date
```


## AC1: SPEC 11.1: each fixture round-trips; zero faithfulness violations on auto-approved blocks

verdict: **VERIFIED**: K3, K12, K13, K14 PASS; faithfulness violations / auto-approved blocks per fixture: clean 0/65, figures 0/57, manual 0/7, scanned 0/86, tables 0/33, twocol 0/44

command: `uv run labor check --keep '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T//labor-acceptance.sUizMT/project-all'`  (exit 0, 629 s)

```
W1029 17:52:34.324000 82815 torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 7708.17it/s]
check                   status      ms  detail
pipeline run            PASS    478530  6 docs ingested, scored, grouped, selected, cleaned
K1 nodes fresh          PASS      2103  6 docs x 7 nodes fresh
K2 artifacts validate   PASS      1423  621 blocks, 25 sidecars, selection 537 blocks
K3 faithfulness         PASS      1133  0 violations in 189 auto-approved cleaned blocks
K4 block accounting     PASS       295  621 blocks each in exactly one group per view
K5 figures resolve      PASS         6  48 attachments resolved; 0 unresolved caption refs (reported)
K6 idempotent rerun     PASS      8950  48 stage calls, all skip; 197 files unchanged
K7 mock only            PASS         3  465 LLM calls, all mock
K8 state                PASS         9  integrity ok, 1 actions monotonic, selection == DB
K9 baseline learning    PASS        13  learning provenance = baseline
K10 export gate         PASS      4518  refused with 329 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS    118078  329 blocks approved by a scripted reviewer; exported 52 articles
K12 zip validates       PASS       291  52 articles, 25 figures, 611728 bytes
K13 export accounting   PASS       265  621 blocks: 537 in articles, 84 unassigned
K14 round trip          PASS      1190  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 86 | 0 | 11 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 44 | 0 | 8 | 3
K15 export determinism  PASS      5565  sha256 12a04817641542c5 identical on a second export
K16 figure references   PASS       102  48 figure references resolve to a file and a sidecar

kept /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-8zhk95aa/project-all

labor check: all checks passed
```


## AC2: SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall)

verdict: **VERIFIED**: recall 24/24 at threshold 0.85

command: `uv run pytest tests/scoring -m acc2 -s -q`  (exit 0, 471 s)

```
W1029 18:03:14.890000 91732 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 11087.20it/s]

SPEC 11.2 scanned recall 1.000 (24/24 differing blocks below 0.85); queue recall 24/24; below threshold 48/154; review load (queued) 90/154
RECALL 24/24 at threshold 0.85
.
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp: 183 MiB

=============================== warnings summary ===============================
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

tests/scoring/test_recall_scanned.py::test_scanned_recall
tests/scoring/test_recall_scanned.py::test_scanned_recall
tests/scoring/test_recall_scanned.py::test_scanned_recall
tests/scoring/test_recall_scanned.py::test_scanned_recall
tests/scoring/test_recall_scanned.py::test_scanned_recall
tests/scoring/test_recall_scanned.py::test_scanned_recall
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/pydantic/main.py:587: DeprecationWarning: `force_full_page_ocr` is deprecated; set `mode=OcrMode.FULL_PAGE` instead.
    return self.__pydantic_serializer__.to_json(

tests/scoring/test_recall_scanned.py::test_scanned_recall
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/docling/pipeline/standard_pdf_pipeline.py:638: DeprecationWarning: This field is deprecated. Use `generate_page_images=True` and call `TableItem.get_image()` to extract table images from page images.
    or self.pipeline_options.generate_table_images

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```


## AC3: SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly

verdict: **VERIFIED**: native=8 vector=6 crop=0 (100%); caption refs clean 3/3, twocol 3/3, figures 12/12, scanned 3/3, manual 2/2

command: `uv run pytest tests/figures tests/cleanup -m acc3 -s -q`  (exit 0, 225 s)

```
W1029 18:10:56.289000 651 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights:  90%|█████████ | 695/770 [00:00<00:00, 6946.53it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 7085.98it/s]
FIGURES native=8 vector=6 crop=0 (native+vector 14/14)
.
clean: caption_ref 3/3 GT references
ATTACH ok 3/3 (clean)
.
twocol: caption_ref 3/3 GT references
ATTACH ok 3/3 (twocol)
.
figures: caption_ref 12/12 GT references
ATTACH ok 12/12 (figures)
.
scanned: caption_ref 3/3 GT references
ATTACH ok 3/3 (scanned)
.
manual: caption_ref 2/2 GT references
ATTACH ok 2/2 (manual)
.
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp: 276 MiB

=============================== warnings summary ===============================
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

tests/figures/test_gate.py::test_01_figures_methods_match_gt
tests/figures/test_gate.py::test_01_figures_methods_match_gt
tests/figures/test_gate.py::test_01_figures_methods_match_gt
tests/figures/test_gate.py::test_01_figures_methods_match_gt
tests/figures/test_gate.py::test_01_figures_methods_match_gt
tests/figures/test_gate.py::test_01_figures_methods_match_gt
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/pydantic/main.py:587: DeprecationWarning: `force_full_page_ocr` is deprecated; set `mode=OcrMode.FULL_PAGE` instead.
    return self.__pydantic_serializer__.to_json(

tests/figures/test_gate.py::test_01_figures_methods_match_gt
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/docling/pipeline/standard_pdf_pipeline.py:638: DeprecationWarning: This field is deprecated. Use `generate_page_images=True` and call `TableItem.get_image()` to extract table images from page images.
    or self.pipeline_options.generate_table_images

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```


## AC4: SPEC 11.4: 20 queued blocks processed with the keyboard only

verdict: **VERIFIED**: 1 passed (Playwright)

command: `cd frontend && npm run e2e -- --grep '@AC4'`  (exit 0, 97 s)

```
[... 17 earlier lines omitted ...]
[WebServer] {"detail":null,"doc":"clean","elapsed_ms":3,"node":"parse","pages":12,"stage":"order","status":"done"}
[WebServer] {"detail":"150 blocks","doc":"clean","elapsed_ms":null,"node":"parse","pages":12,"stage":"ids","status":"done"}
[WebServer] {"detail":null,"doc":"clean","elapsed_ms":15,"node":"parse","pages":12,"stage":"ocr_attach","status":"done"}
[WebServer] {"detail":"150 blocks","doc":"clean","elapsed_ms":29,"node":"parse","pages":12,"stage":"write","status":"done"}
[WebServer] {"doc":"clean","elapsed_ms":11271,"event":"unit_done","node":"parse","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":788,"node":"parse","pages":8,"stage":"pymupdf","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":2575,"node":"parse","pages":8,"stage":"docling","status":"done"}
[WebServer] {"detail":"8 rendered, 1546 ms in workers","doc":"figures","elapsed_ms":null,"node":"parse","pages":8,"stage":"render","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":6007,"node":"parse","pages":8,"stage":"ocr","status":"done"}
[WebServer] {"detail":"95 candidates merged","doc":"figures","elapsed_ms":5,"node":"parse","pages":8,"stage":"merge","status":"done"}
[WebServer] {"detail":"8 headers, 8 footers","doc":"figures","elapsed_ms":0,"node":"parse","pages":8,"stage":"headers","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":2,"node":"parse","pages":8,"stage":"order","status":"done"}
[WebServer] {"detail":"95 blocks","doc":"figures","elapsed_ms":null,"node":"parse","pages":8,"stage":"ids","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":6,"node":"parse","pages":8,"stage":"ocr_attach","status":"done"}
[WebServer] {"detail":"95 blocks","doc":"figures","elapsed_ms":15,"node":"parse","pages":8,"stage":"write","status":"done"}
[WebServer] {"doc":"figures","elapsed_ms":6210,"event":"unit_done","node":"parse","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":545,"node":"parse","pages":12,"stage":"pymupdf","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":3939,"node":"parse","pages":12,"stage":"docling","status":"done"}
[WebServer] {"detail":"12 rendered, 14187 ms in workers","doc":"scanned","elapsed_ms":null,"node":"parse","pages":12,"stage":"render","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":53615,"node":"parse","pages":12,"stage":"ocr","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":null,"node":"parse","pages":12,"stage":"ocr_alt","status":"done"}
[WebServer] {"detail":"179 candidates merged","doc":"scanned","elapsed_ms":15,"node":"parse","pages":12,"stage":"merge","status":"done"}
[WebServer] {"detail":"11 headers, 11 footers","doc":"scanned","elapsed_ms":1,"node":"parse","pages":12,"stage":"headers","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":4,"node":"parse","pages":12,"stage":"order","status":"done"}
[WebServer] {"detail":"179 blocks","doc":"scanned","elapsed_ms":null,"node":"parse","pages":12,"stage":"ids","status":"done"}
[WebServer] {"detail":"179 blocks","doc":"scanned","elapsed_ms":31,"node":"parse","pages":12,"stage":"write","status":"done"}
[WebServer] {"doc":"scanned","elapsed_ms":53955,"event":"unit_done","node":"parse","status":"done"}
[WebServer] {"by_method":{"crop":0,"native":3,"vector":0},"detail":null,"doc":"clean","elapsed_ms":106,"failures":0,"figures":3,"node":"figures","stage":"figures","status":"done"}
[WebServer] {"exact":0,"near":0,"node":"figures","stage":"figures_dedupe","status":"done"}
[WebServer] {"doc":"clean","elapsed_ms":109,"event":"unit_done","node":"figures","status":"done"}
[WebServer] {"by_method":{"crop":0,"native":8,"vector":6},"detail":null,"doc":"figures","elapsed_ms":347,"failures":0,"figures":14,"node":"figures","stage":"figures","status":"done"}
[WebServer] {"exact":1,"near":1,"node":"figures","stage":"figures_dedupe","status":"done"}
[WebServer] {"doc":"figures","elapsed_ms":353,"event":"unit_done","node":"figures","status":"done"}
[WebServer] {"by_method":{"crop":3,"native":0,"vector":0},"detail":null,"doc":"scanned","elapsed_ms":167,"failures":0,"figures":3,"node":"figures","stage":"figures","status":"done"}
[WebServer] {"exact":1,"near":4,"node":"figures","stage":"figures_dedupe","status":"done"}
[WebServer] {"doc":"scanned","elapsed_ms":172,"event":"unit_done","node":"figures","status":"done"}
[WebServer] {"auto_approved":65,"blocks":150,"detail":null,"doc":"clean","elapsed_ms":129,"faith_failed":0,"figures":3,"node":"score","numeric":85,"queued":85,"stage":"score","status":"done"}
[WebServer] {"doc":"clean","elapsed_ms":130,"event":"unit_done","node":"score","status":"done"}
[WebServer] {"auto_approved":58,"blocks":95,"detail":null,"doc":"figures","elapsed_ms":66,"faith_failed":0,"figures":14,"node":"score","numeric":36,"queued":37,"stage":"score","status":"done"}
[WebServer] {"doc":"figures","elapsed_ms":66,"event":"unit_done","node":"score","status":"done"}
[WebServer] {"auto_approved":86,"blocks":179,"detail":null,"doc":"scanned","elapsed_ms":110,"faith_failed":0,"figures":3,"node":"score","numeric":86,"queued":93,"stage":"score","status":"done"}
[WebServer] {"doc":"scanned","elapsed_ms":111,"event":"unit_done","node":"score","status":"done"}
[WebServer] {"detail":null,"doc":"clean","elapsed_ms":229,"llm_fallbacks":0,"low_cohesion":7,"node":"group","stage":"group","status":"done","stragglers":1,"structure_groups":18,"topics":14,"unassigned":1}
[WebServer] {"doc":"clean","elapsed_ms":229,"event":"unit_done","node":"group","status":"done"}
[WebServer] {"detail":null,"doc":"figures","elapsed_ms":38,"llm_fallbacks":0,"low_cohesion":2,"node":"group","stage":"group","status":"done","stragglers":1,"structure_groups":8,"topics":5,"unassigned":0}
[WebServer] {"doc":"figures","elapsed_ms":39,"event":"unit_done","node":"group","status":"done"}
[WebServer] {"detail":null,"doc":"scanned","elapsed_ms":80,"llm_fallbacks":0,"low_cohesion":2,"node":"group","stage":"group","status":"done","stragglers":4,"structure_groups":18,"topics":11,"unassigned":0}
[WebServer] {"doc":"scanned","elapsed_ms":81,"event":"unit_done","node":"group","status":"done"}
[WebServer] {"by_stage":{"deterministic":95,"raw":30},"changed":95,"cleaned":125,"det_rejected":0,"detail":null,"doc":"clean","elapsed_ms":135,"llm_accepted":0,"llm_cached":0,"llm_calls":0,"llm_rejected":{},"node":"clean","residual":{},"selected":128,"stage":"clean","status":"done"}
[WebServer] {"attached":3,"by_rule":{"caption_ref":3},"detail":"3 sidecars updated","doc":"clean","elapsed_ms":4,"figures":3,"node":"clean","overrides_stale":0,"stage":"attach","status":"done","unattached":0,"unresolved_refs":0}
[WebServer] {"described":3,"detail":null,"doc":"clean","elapsed_ms":3,"errors":0,"invalid":0,"node":"clean","skipped":0,"stage":"describe","status":"done"}
[WebServer] {"doc":"clean","elapsed_ms":158,"event":"unit_done","node":"clean","status":"done"}
[WebServer] {"by_stage":{"deterministic":44,"raw":21},"changed":44,"cleaned":65,"det_rejected":0,"detail":null,"doc":"figures","elapsed_ms":64,"llm_accepted":0,"llm_cached":0,"llm_calls":0,"llm_rejected":{},"node":"clean","residual":{},"selected":79,"stage":"clean","status":"done"}
[WebServer] {"attached":14,"by_rule":{"caption_match":1,"caption_ref":12,"proximity":1},"detail":"14 sidecars updated","doc":"figures","elapsed_ms":6,"figures":14,"node":"clean","overrides_stale":0,"stage":"attach","status":"done","unattached":0,"unresolved_refs":0}
[WebServer] {"described":14,"detail":null,"doc":"figures","elapsed_ms":9,"errors":0,"invalid":0,"node":"clean","skipped":0,"stage":"describe","status":"done"}
[WebServer] {"doc":"figures","elapsed_ms":87,"event":"unit_done","node":"clean","status":"done"}
[WebServer] {"by_stage":{"deterministic":102,"raw":52},"changed":102,"cleaned":154,"det_rejected":0,"detail":null,"doc":"scanned","elapsed_ms":136,"llm_accepted":0,"llm_cached":0,"llm_calls":0,"llm_rejected":{},"node":"clean","residual":{},"selected":157,"stage":"clean","status":"done"}
[WebServer] {"attached":3,"by_rule":{"caption_ref":3},"detail":"3 sidecars updated","doc":"scanned","elapsed_ms":3,"figures":3,"node":"clean","overrides_stale":0,"stage":"attach","status":"done","unattached":0,"unresolved_refs":0}
[WebServer] {"described":3,"detail":null,"doc":"scanned","elapsed_ms":2,"errors":0,"invalid":0,"node":"clean","skipped":0,"stage":"describe","status":"done"}
[WebServer] {"doc":"scanned","elapsed_ms":157,"event":"unit_done","node":"clean","status":"done"}
[WebServer] {"auto_approved":65,"blocks":150,"detail":"verifier_ok: 95; verifier skipped: 30","doc":"clean","elapsed_ms":239,"faith_failed":0,"figures":3,"node":"score2","numeric":85,"queued":85,"stage":"score","status":"done"}
[WebServer] {"doc":"clean","elapsed_ms":240,"event":"unit_done","node":"score2","status":"done"}
[WebServer] {"auto_approved":57,"blocks":95,"detail":"verifier_ok: 44; verifier skipped: 21","doc":"figures","elapsed_ms":115,"faith_failed":0,"figures":14,"node":"score2","numeric":36,"queued":38,"stage":"score","status":"done"}
[WebServer] {"doc":"figures","elapsed_ms":115,"event":"unit_done","node":"score2","status":"done"}
[WebServer] {"auto_approved":86,"blocks":179,"detail":"verifier_ok: 102; verifier skipped: 52","doc":"scanned","elapsed_ms":219,"faith_failed":0,"figures":3,"node":"score2","numeric":86,"queued":93,"stage":"score","status":"done"}
[WebServer] {"doc":"scanned","elapsed_ms":220,"event":"unit_done","node":"score2","status":"done"}
[WebServer] e2e-project: built in 77s
[WebServer]   clean: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer]   figures: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer]   scanned: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer] labor serve: http://127.0.0.1:8765  (project /private/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/ml-e2e-Tb2yfi/project)
[WebServer] e2e-project: cache hit (/Users/ashwinchidambaram/dev/projects/doc-to-KB/frontend/e2e/.cache), preconditions hold

Running 1 test using 1 worker

VE1 plan 0:A:b-scanned-p009-10 1:A:b-scanned-p002-11 2:EDIT_OK:b-scanned-p008-10 3:A:b-scanned-p003-15 4:FLAG1:b-scanned-p007-05 5:A:b-scanned-p001-02 6:SKIP:b-scanned-p010-17 7:A:b-scanned-p004-16 8:EDIT_409:b-scanned-p010-06 9:A:b-scanned-p011-04 10:AKA:b-scanned-p002-06 11:A:b-scanned-p002-14 12:FLAG5:b-scanned-p012-11 13:A:b-scanned-p007-04 14:A:b-scanned-p002-04 15:A:b-scanned-p002-16 16:A:b-scanned-p009-11 17:A:b-scanned-p003-16 18:A:b-scanned-p008-16 19:A:b-scanned-p009-07
VE1 server-side decision counts {"approve":16,"edit":2,"flag":2,"skip":1,"back":1}
  ✓  1 [chromium] › e2e/verify.spec.ts:65:1 › VE1 twenty blocks keyboard-only (gate) @AC4 (5.1s)

  1 passed (1.6m)
```


## AC5: SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results

verdict: **VERIFIED**: PROPOSALS 5/5 with checks

command: `uv run pytest tests/agent -m acc5 -s -q`  (exit 0, 23 s)

```
W1029 18:16:02.439000 6620 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 20840.12it/s]
PROPOSALS 5/5 with checks
.
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp: 16 MiB

=============================== warnings summary ===============================
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/agent/test_pass.py::test_1_five_seeded_flags_five_proposals
tests/agent/test_pass.py::test_1_five_seeded_flags_five_proposals
tests/agent/test_pass.py::test_1_five_seeded_flags_five_proposals
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/pydantic/main.py:587: DeprecationWarning: `force_full_page_ocr` is deprecated; set `mode=OcrMode.FULL_PAGE` instead.
    return self.__pydantic_serializer__.to_json(

tests/agent/test_pass.py::test_1_five_seeded_flags_five_proposals
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/docling/pipeline/standard_pdf_pipeline.py:638: DeprecationWarning: This field is deprecated. Use `generate_page_images=True` and call `TableItem.get_image()` to extract table images from page images.
    or self.pipeline_options.generate_table_images

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```


## AC6: SPEC 11.6: Scope toggle preserves selection and shows correct coverage

verdict: **VERIFIED**: 1 passed (Playwright)

command: `cd frontend && npm run e2e -- --grep '@AC6'`  (exit 0, 12 s)

```

> manuallabor-ui@0.1.0 e2e
> playwright test --grep @AC6

[WebServer] e2e-project: cache hit (/Users/ashwinchidambaram/dev/projects/doc-to-KB/frontend/e2e/.cache), preconditions hold
[WebServer]   clean: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer]   figures: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer]   scanned: ingest=fresh parse=fresh figures=fresh score=fresh group=fresh clean=fresh score2=fresh
[WebServer] labor serve: http://127.0.0.1:8765  (project /private/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/ml-e2e-g84Gnu/project)
[WebServer] e2e-project: cache hit (/Users/ashwinchidambaram/dev/projects/doc-to-KB/frontend/e2e/.cache), preconditions hold

Running 1 test using 1 worker

  ✓  1 [chromium] › e2e/scope.spec.ts:27:1 › E1 toggle preserves selection and shows coverage in the other view @AC6 (1.3s)

  1 passed (11.4s)
```


## AC7: SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar

verdict: **VERIFIED**: 124 passed, 1 skipped (counted from the progress line); OK: 52 articles, 25 figures; zip sha256 12a04817641542c5e08cd13bbdd259dd1f528fd4b0ed0e4f56d6dc4833bf3086

command: `uv run pytest tests/export -q`  (exit 0, 174 s)

```
..................s..................................................... [ 57%]
.....................................................                    [100%]
=============================== warnings summary ===============================
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

<frozen importlib._bootstrap>:488
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute
```

command: `uv run labor validate-export '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-8zhk95aa/project-all/export/project-a-kb.zip'`  (exit 0, 1 s)

```
OK: 52 articles, 25 figures
```

command: `shasum -a 256 '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-8zhk95aa/project-all/export/project-a-kb.zip'`  (exit 0, 0 s)

```
12a04817641542c5e08cd13bbdd259dd1f528fd4b0ed0e4f56d6dc4833bf3086  /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-8zhk95aa/project-all/export/project-a-kb.zip
```


## AC8: SPEC 11.8: fully local run (Ollama), network disabled

verdict: **VERIFIED**: 0 network violations; ollama=464 other=0; negative control: 1.1.1.1:443 blocked and logged

command: `ollama list`  (exit 0, 1 s)

```
NAME                       ID              SIZE      MODIFIED     
qwen2.5:1.5b               65ec06548149    986 MB    10 hours ago    
moondream:latest           55fc3abd3867    1.7 GB    11 hours ago    
llama3.2:1b                baf6a787fdff    1.3 GB    11 hours ago    
nomic-embed-text:latest    0a109f422b47    274 MB    7 weeks ago     
```

command: `MANUALLABOR_OFFLINE=1 MANUALLABOR_OFFLINE_LOG='/Users/ashwinchidambaram/dev/projects/doc-to-KB/build/acceptance/net.log' uv run labor check --live --keep '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T//labor-acceptance.sUizMT/project-all'`  (exit 0, 1314 s)

```
W1029 18:19:46.917000 9946 torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights:  97%|█████████▋| 748/770 [00:00<00:00, 7476.64it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 7550.50it/s]
check                   status      ms  detail
pipeline run            PASS    1261695  6 docs ingested, scored, grouped, selected, cleaned
K1 nodes fresh          PASS      2012  6 docs x 7 nodes fresh
K2 artifacts validate   PASS       641  621 blocks, 25 sidecars, selection 537 blocks
K3 faithfulness         PASS      1306  0 violations in 186 auto-approved cleaned blocks
K4 block accounting     PASS       266  621 blocks each in exactly one group per view
K5 figures resolve      PASS         6  43 attachments resolved; 0 unresolved caption refs (reported)
K6 idempotent rerun     PASS      9058  48 stage calls, all skip; 197 files unchanged
K7 mock only            SKIP         0  live mode
K8 state                PASS         8  integrity ok, 1 actions monotonic, selection == DB
K9 baseline learning    PASS        10  learning provenance = baseline
K10 export gate         PASS      3093  refused with 332 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS     28134  332 blocks approved by a scripted reviewer; exported 48 articles
K12 zip validates       PASS        47  48 articles, 25 figures, 609893 bytes
K13 export accounting   PASS        51  621 blocks: 537 in articles, 84 unassigned
K14 round trip          PASS       130  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 9 | 3; figures | 95 | 57 | 0 | 8 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 85 | 0 | 8 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 42 | 0 | 10 | 3
K15 export determinism  PASS      1070  sha256 153845dd74504dac identical on a second export
K16 figure references   PASS        18  43 figure references resolve to a file and a sidecar

kept /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-luuxuwma/project-all

labor check: all checks passed
```

command: `if [ -s '/Users/ashwinchidambaram/dev/projects/doc-to-KB/build/acceptance/net.log' ]; then echo 'network violations:'; cat '/Users/ashwinchidambaram/dev/projects/doc-to-KB/build/acceptance/net.log'; exit 1; else echo '0 network violations'; fi`  (exit 0, 0 s)

```
0 network violations
```

command: `uv run python scripts/render_acceptance.py providers '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-luuxuwma/project-all/llm_calls.jsonl'`  (exit 0, 1 s)

```
ollama=464 other=0
```

command: `MANUALLABOR_OFFLINE=1 MANUALLABOR_OFFLINE_LOG='/Users/ashwinchidambaram/dev/projects/doc-to-KB/build/acceptance/net-control.log' uv run python scripts/offline_control.py`  (exit 0, 0 s)

```
negative control: 1.1.1.1:443 blocked and logged (/Users/ashwinchidambaram/dev/projects/doc-to-KB/build/acceptance/net-control.log)
```
