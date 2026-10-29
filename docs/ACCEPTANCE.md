# Acceptance record (SPEC section 11)

status: INCOMPLETE
generated: 2026-10-29T16:42:06Z
tool version: 0.1.0
uv.lock sha256: 0d95ec27a725beb9feb6183680ef8d310431115b715e8278c0749e17a2374f6f
host: Darwin 25.5.0 arm64, 16.0 GiB RAM
mode: mock (no --live)
total wall time: 2268 s

Every line below is output pasted from the command that produced it. NOT VERIFIED means the step did not run or printed no evidence; it is not a pass.

| AC | item | verdict | evidence |
|---|---|---|---|
| 0 | Machine checks: tests, lint, types, JSON schemas, OpenAPI | **FAILED** | 0-1 exited 1 |
| 1 | SPEC 11.1: each fixture round-trips; zero faithfulness violations on auto-approved blocks | **VERIFIED** | K3, K12, K13, K14 PASS; 316 doc / blocks / auto_approved / faith_violations(auto) / articles / figures: clean / 150 / 65 / 0 / 15 / 3; figures / 95 / 57 / 0 / 5 / 14; manual / 13 / 7 / 0 / 3 / 2; scanned / 179 / 86 / 0 / 11 / 3; tables / 87 / 33 / 0 / 10 / 0; twocol / 97 / 44 / 0 / 8 / 3 |
| 2 | SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall) | **VERIFIED** | recall 24/24 at threshold 0.85 |
| 3 | SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly | **FAILED** | 3-1 exited 2 |
| 4 | SPEC 11.4: 20 queued blocks processed with the keyboard only | **NOT VERIFIED** | the step did not run (skipped or its input was not produced) |
| 5 | SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results | **FAILED** | 5-1 exited 2 |
| 6 | SPEC 11.6: Scope toggle preserves selection and shows correct coverage | **NOT VERIFIED** | the step did not run (skipped or its input was not produced) |
| 7 | SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar | **FAILED** | 7-1 exited 1 |
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

verdict: **VERIFIED**: K3, K12, K13, K14 PASS; 316 doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 86 | 0 | 11 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 44 | 0 | 8 | 3

command: `uv run labor check --keep '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T//labor-acceptance.vwoXUa/project-all'`  (exit 0, 169 s)

```
W1029 13:02:50.241000 74149 torch/distributed/elastic/multiprocessing/redirects.py:35] NOTE: Redirects are currently not supported in MacOs.

Loading weights:   0%|          | 0/770 [00:00<?, ?it/s]
Loading weights: 100%|██████████| 770/770 [00:00<00:00, 10830.87it/s]
check                   status      ms  detail
pipeline run            PASS    132808  6 docs ingested, scored, grouped, selected, cleaned
K1 nodes fresh          PASS       581  6 docs x 7 nodes fresh
K2 artifacts validate   PASS       364  621 blocks, 25 sidecars, selection 537 blocks
K3 faithfulness         PASS       303  0 violations in 189 auto-approved cleaned blocks
K4 block accounting     PASS        69  621 blocks each in exactly one group per view
K5 figures resolve      PASS         1  48 attachments resolved; 0 unresolved caption refs (reported)
K6 idempotent rerun     PASS      2882  48 stage calls, all skip; 197 files unchanged
K7 mock only            PASS         3  465 LLM calls, all mock
K8 state                PASS         2  integrity ok, 1 actions monotonic, selection == DB
K9 baseline learning    PASS         3  learning provenance = baseline
K10 export gate         PASS      2483  refused with 329 queued block(s), 0 open flag(s); first b-clean-p002-04
K11 review + export     PASS     26598  329 blocks approved by a scripted reviewer; exported 52 articles
K12 zip validates       PASS        40  52 articles, 25 figures, 611727 bytes
K13 export accounting   PASS        59  621 blocks: 537 in articles, 84 unassigned
K14 round trip          PASS       316  doc | blocks | auto_approved | faith_violations(auto) | articles | figures: clean | 150 | 65 | 0 | 15 | 3; figures | 95 | 57 | 0 | 5 | 14; manual | 13 | 7 | 0 | 3 | 2; scanned | 179 | 86 | 0 | 11 | 3; tables | 87 | 33 | 0 | 10 | 0; twocol | 97 | 44 | 0 | 8 | 3
K15 export determinism  PASS      1130  sha256 bf3937a1cc17600d identical on a second export
K16 figure references   PASS         1  48 figure references resolve to a file and a sidecar

kept /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-seae_5a1/project-all

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

verdict: **FAILED**: 3-1 exited 2

command: `uv run pytest -m acc3 -s -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 2, 2 s)

```
/Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa

==================================== ERRORS ====================================
______________ ERROR collecting tests/agent/test_review_fixes.py _______________
ImportError while importing test module '/Users/ashwinchidambaram/dev/projects/doc-to-KB/tests/agent/test_review_fixes.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/agent/test_review_fixes.py:10: in <module>
    from manuallabor.agent.recheck import (
E   ImportError: cannot import name 'check_table_position' from 'manuallabor.agent.recheck' (/Users/ashwinchidambaram/dev/projects/doc-to-KB/manuallabor/agent/recheck.py)
=========================== short test summary info ============================
ERROR tests/agent/test_review_fixes.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```


## AC4: SPEC 11.4: 20 queued blocks processed with the keyboard only

verdict: **NOT VERIFIED**: the step did not run (skipped or its input was not produced)

No step ran for this item.


## AC5: SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results

verdict: **FAILED**: 5-1 exited 2

command: `uv run pytest -m acc5 -s -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 2, 2 s)

```
/Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa

==================================== ERRORS ====================================
______________ ERROR collecting tests/agent/test_review_fixes.py _______________
ImportError while importing test module '/Users/ashwinchidambaram/dev/projects/doc-to-KB/tests/agent/test_review_fixes.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/agent/test_review_fixes.py:10: in <module>
    from manuallabor.agent.recheck import (
E   ImportError: cannot import name 'check_table_position' from 'manuallabor.agent.recheck' (/Users/ashwinchidambaram/dev/projects/doc-to-KB/manuallabor/agent/recheck.py)
=========================== short test summary info ============================
ERROR tests/agent/test_review_fixes.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```


## AC6: SPEC 11.6: Scope toggle preserves selection and shows correct coverage

verdict: **NOT VERIFIED**: the step did not run (skipped or its input was not produced)

No step ran for this item.


## AC7: SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar

verdict: **FAILED**: 7-1 exited 1

command: `uv run pytest tests/export -q --basetemp=.pytest_tmp_m11 -p no:warnings`  (exit 1, 728 s)

```
.....F..s...........F................................................... [ 81%]
................                                                         [100%]
=================================== FAILURES ===================================
_________ test_e23_and_e25_labor_check_runs_the_export_stages_offline __________

requires_docling = None
tmp_path = PosixPath('/Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11/test_e23_and_e25_labor_check_r0')

    def test_e23_and_e25_labor_check_runs_the_export_stages_offline(
        requires_docling: None, tmp_path: Path
    ) -> None:
>       before_tree, before_tmp = tree_hash(PROJECT_A), temp_dirs()
                                                        ^^^^^^^^^^^
E       TypeError: temp_dirs() missing 1 required positional argument: 'root'

tests/export/test_check_stages.py:23: TypeError
________ test_e14_zip_is_byte_identical_across_processes_and_hash_seeds ________

approved_a = ProjectPaths(root=PosixPath('/Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11/export-a-approved0/proj'))
tmp_path = PosixPath('/Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11/test_e14_zip_is_byte_identical0')

    def test_e14_zip_is_byte_identical_across_processes_and_hash_seeds(
        approved_a: ProjectPaths, tmp_path: Path
    ) -> None:
        from tests.conftest import labor_copy
    
        outs = []
        for i, seed in enumerate(("1", "99")):
            p = ProjectPaths(labor_copy(approved_a.root, tmp_path / f"p{i}", db=True))
>           r = labor("export", str(p.root), "--now", CLOCK, env={"PYTHONHASHSEED": seed})
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/export/test_pipeline.py:167: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/export/test_pipeline.py:39: in labor
    return subprocess.run(LABOR + list(args), capture_output=True, text=True, timeout=600, env=e)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/subprocess.py:550: in run
    stdout, stderr = process.communicate(input, timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/subprocess.py:1209: in communicate
    stdout, stderr = self._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/subprocess.py:2116: in _communicate
    self._check_timeout(endtime, orig_timeout, stdout, stderr)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <Popen: returncode: -9 args: ['/Users/ashwinchidambaram/dev/projects/doc-to-...>
endtime = 546059.010038625, orig_timeout = 600
stdout_seq = [b'{"articles":20,"doc":"","figures":17,"stage":"assemble","status":"built"}\n', b'{"articles":20,"doc":"","figures":1...zip: 20 articles, 17 figures, 455799 bytes\nsha256 a53de0326f07949d1c23066992470e5bcabd3914b73f1ea5c938596bd897d882\n']
stderr_seq = [], skip_check_and_raise = False

    def _check_timeout(self, endtime, orig_timeout, stdout_seq, stderr_seq,
                       skip_check_and_raise=False):
        """Convenience for checking if a timeout has expired."""
        if endtime is None:
            return
        if skip_check_and_raise or _time() > endtime:
>           raise TimeoutExpired(
                    self.args, orig_timeout,
                    output=b''.join(stdout_seq) if stdout_seq else None,
                    stderr=b''.join(stderr_seq) if stderr_seq else None)
E           subprocess.TimeoutExpired: Command '['/Users/ashwinchidambaram/dev/projects/doc-to-KB/.venv/bin/python', '-m', 'manuallabor', 'export', '/Users/ashwinchidambaram/dev/projects/doc-to-KB/.pytest_tmp_m11/test_e14_zip_is_byte_identical0/p1', '--now', '2026-10-29T12:00:00Z']' timed out after 600 seconds

../../../.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12/subprocess.py:1253: TimeoutExpired
=========================== short test summary info ============================
FAILED tests/export/test_check_stages.py::test_e23_and_e25_labor_check_runs_the_export_stages_offline
FAILED tests/export/test_pipeline.py::test_e14_zip_is_byte_identical_across_processes_and_hash_seeds
```

command: `uv run labor validate-export '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-seae_5a1/project-all/export/project-a-kb.zip'`  (exit 0, 0 s)

```
OK: 52 articles, 25 figures
```

command: `shasum -a 256 '/var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-seae_5a1/project-all/export/project-a-kb.zip'`  (exit 0, 0 s)

```
bf3937a1cc17600d19c98136ed81bb34e672c3fa2057d9eb8f6f59d073f2e98e  /var/folders/2j/kdqlsp910vlcpdjcjhp13km40000gn/T/labor-check-seae_5a1/project-all/export/project-a-kb.zip
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
