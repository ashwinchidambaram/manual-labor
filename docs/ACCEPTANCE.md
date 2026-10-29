# Acceptance record (SPEC section 11)

status: INCOMPLETE
generated: 2026-10-29T17:39:11Z
tool version: 0.1.0
uv.lock sha256: 0d95ec27a725beb9feb6183680ef8d310431115b715e8278c0749e17a2374f6f
host: Darwin 25.5.0 arm64, 16.0 GiB RAM
mode: mock (no --live)
total wall time: 0 s

Every line below is output pasted from the command that produced it. NOT VERIFIED means the step did not run or printed no evidence; it is not a pass.

| AC | item | verdict | evidence |
|---|---|---|---|
| 0 | Machine checks: tests, lint, types, JSON schemas, OpenAPI | **FAILED** | 0-1 exited 1 |
| 1 | SPEC 11.1: each fixture round-trips; zero faithfulness violations on auto-approved blocks | **VERIFIED** | K3, K12, K13, K14 PASS; faithfulness violations / auto-approved blocks per fixture: clean 0/65, figures 0/57, manual 0/7, scanned 0/86, tables 0/33, twocol 0/44 |
| 2 | SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall) | **VERIFIED** | recall 24/24 at threshold 0.85 |
| 3 | SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly | **VERIFIED** | native=8 vector=6 crop=0 (100%); caption refs clean 3/3, twocol 3/3, figures 12/12, scanned 3/3, manual 2/2 |
| 4 | SPEC 11.4: 20 queued blocks processed with the keyboard only | **NOT VERIFIED** | the step did not run (skipped or its input was not produced) |
| 5 | SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results | **VERIFIED** | PROPOSALS 5/5 with checks |
| 6 | SPEC 11.6: Scope toggle preserves selection and shows correct coverage | **NOT VERIFIED** | the step did not run (skipped or its input was not produced) |
| 7 | SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar | **VERIFIED** | 97 passed, 1 skipped (counted from the progress line); OK: 52 articles, 25 figures; zip sha256 bf3937a1cc17600d19c98136ed81bb34e672c3fa2057d9eb8f6f59d073f2e98e |
| 8 | SPEC 11.8: fully local run (Ollama), network disabled | **NOT VERIFIED** | scripts/acceptance.sh was not run with --live (Ollama models required) |

## AC0: Machine checks: tests, lint, types, JSON schemas, OpenAPI

verdict: **FAILED**: 0-1 exited 1

command: `uv run pytest -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 1, 1231 s)

```
[... 58 earlier lines omitted ...]
tests/providers/test_providers.py:102: Failed
=========================== short test summary info ============================
FAILED tests/api/test_routes.py::test_a14_non_blocking - AssertionError: docling
FAILED tests/fixtures_gen/test_fixtures.py::test_f2_regeneration_is_byte_identical
FAILED tests/providers/test_providers.py::test_p6_no_response - Failed: DID N...
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

command: `uv run labor check --keep '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T//labor-acceptance.ow6mks/project-all'`  (exit 0, 168 s)

```
W1029 13:33:51.016000 32018 torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 25869.20it/s]
check                   status      ms  detail
pipeline run            PASS    126942  6 docs ingested, scored, grouped, selected, cleaned
K1 nodes fresh          PASS       809  6 docs x 7 nodes fresh
K2 artifacts validate   PASS       496  621 blocks, 25 sidecars, selection 537 blocks
K3 faithfulness         PASS       488  0 violations in 189 auto-approved cleaned blocks
K4 block accounting     PASS        93  621 blocks each in exactly one group per view
K5 figures resolve      PASS         1  48 attachments resolved; 0 unresolved caption refs (reported)
K6 idempotent rerun     PASS      4956  48 stage calls, all skip; 197 files unchanged
K7 mock only            PASS         2  465 LLM calls, all mock
K8 state                PASS         2  integrity ok, 1 actions monotonic, selection == DB
K9 baseline learning    PASS         2  learning provenance = baseline
K10 export gate         PASS      2852  refused with 329 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS     28226  329 blocks approved by a scripted reviewer; exported 52 articles
K12 zip validates       PASS        37  52 articles, 25 figures, 611727 bytes
K13 export accounting   PASS        54  621 blocks: 537 in articles, 84 unassigned
K14 round trip          PASS       139  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 86 | 0 | 11 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 44 | 0 | 8 | 3
K15 export determinism  PASS      1137  sha256 bf3937a1cc17600d identical on a second export
K16 figure references   PASS         1  48 figure references resolve to a file and a sidecar

kept /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-wjma6sa8/project-all

labor check: all checks passed
```


## AC2: SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall)

verdict: **VERIFIED**: recall 24/24 at threshold 0.85

command: `uv run pytest tests/scoring -m acc2 -s -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 0, 131 s)

```
W1029 13:05:42.187000 78356 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 41440.37it/s]

SPEC 11.2 scanned recall 1.000 (24/24 differing blocks below 0.85); queue recall 24/24; below threshold 48/154; review load (queued) 90/154
RECALL 24/24 at threshold 0.85
.
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11: 183 MiB
```


## AC3: SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly

verdict: **VERIFIED**: native=8 vector=6 crop=0 (100%); caption refs clean 3/3, twocol 3/3, figures 12/12, scanned 3/3, manual 2/2

command: `uv run pytest tests/figures tests/cleanup -m acc3 -s -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 0, 126 s)

```
W1029 13:30:54.915000 25608 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights:  37%|███▋      | 285/770 [00:00<00:00, 2829.60it/s]
Loading weights:  74%|███████▍  | 568/770 [00:00<00:00, 1919.35it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 2707.23it/s]
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
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11: 276 MiB
```


## AC4: SPEC 11.4: 20 queued blocks processed with the keyboard only

verdict: **NOT VERIFIED**: the step did not run (skipped or its input was not produced)

No step ran for this item.


## AC5: SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results

verdict: **VERIFIED**: PROPOSALS 5/5 with checks

command: `uv run pytest tests/agent -m acc5 -s -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 0, 38 s)

```
/Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
W1029 13:33:04.376000 30114 .venv/lib/python3.12/site-packages/torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 36338.02it/s]
PROPOSALS 5/5 with checks
.
[tmp footprint] /Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11: 16 MiB
```


## AC6: SPEC 11.6: Scope toggle preserves selection and shows correct coverage

verdict: **NOT VERIFIED**: the step did not run (skipped or its input was not produced)

No step ran for this item.


## AC7: SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar

verdict: **VERIFIED**: 97 passed, 1 skipped (counted from the progress line); OK: 52 articles, 25 figures; zip sha256 bf3937a1cc17600d19c98136ed81bb34e672c3fa2057d9eb8f6f59d073f2e98e

command: `uv run pytest tests/export -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 0, 150 s)

```
........s............................................................... [ 73%]
..........................                                               [100%]
```

command: `uv run labor validate-export '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-wjma6sa8/project-all/export/project-a-kb.zip'`  (exit 0, 1 s)

```
OK: 52 articles, 25 figures
```

command: `shasum -a 256 '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-wjma6sa8/project-all/export/project-a-kb.zip'`  (exit 0, 0 s)

```
bf3937a1cc17600d19c98136ed81bb34e672c3fa2057d9eb8f6f59d073f2e98e  /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-wjma6sa8/project-all/export/project-a-kb.zip
```


## AC8: SPEC 11.8: fully local run (Ollama), network disabled

verdict: **NOT VERIFIED**: scripts/acceptance.sh was not run with --live (Ollama models required)

To verify, install the small-tier models and re-run with `--live`:

```
ollama pull llama3.2:1b
ollama pull qwen2.5:1.5b
ollama pull moondream
ollama pull nomic-embed-text
bash scripts/acceptance.sh --live
```

No step ran for this item.
